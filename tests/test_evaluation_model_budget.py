from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, select
from test_evaluation_persistence import _database

from packages.evaluation.model_budget import (
    BudgetedDeepSeekGateway,
    recover_uncertain_calls,
    reserve_call,
    settle_call,
)
from packages.evaluation.persistence import EvaluationModelCall
from packages.model_gateway import GatewayMessage, GatewayRequest, ModelGatewayError


def _live(*, max_calls=3, max_tokens=10000, max_seconds=60):
    db, run = _database()
    run.track = "live"
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.model_version = "deepseek-v4-pro"
    run.budget = {"max_calls": max_calls, "max_tokens": max_tokens, "max_seconds": max_seconds}
    db.commit()
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    return db, run, engine


def _response(content='{"value":1}', usage=True):
    data = {
        "id": "synthetic-response",
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
    }
    if usage:
        data["usage"] = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    return httpx.Response(200, json=data)


def _gateway(engine, run, handler):
    return BudgetedDeepSeekGateway(
        engine=engine,
        run_id=run.id,
        call_prefix="case-1",
        api_key="synthetic-not-a-secret",
        model=run.model_version,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_usage_settles_once_and_duplicate_delivery_does_not_send() -> None:
    db, run, engine = _live()
    sent = []

    def handler(request):
        sent.append(request)
        return _response()

    request = GatewayRequest(messages=(GatewayMessage("user", "合成问题"),), max_tokens=100)
    result = _gateway(engine, run, handler).complete(request)
    assert result.usage.total_tokens == 30
    db.expire_all()
    assert (run.calls_used, run.tokens_used, run.calls_reserved, run.tokens_reserved) == (
        1,
        30,
        0,
        0,
    )
    receipt = db.scalar(select(EvaluationModelCall))
    assert receipt is not None and receipt.status == "settled"
    settle_call(engine, receipt.id, 30)
    with pytest.raises(ModelGatewayError, match="call_already_recorded"):
        _gateway(engine, run, handler).complete(request)
    assert len(sent) == 1
    db.expire_all()
    assert run.calls_used == 1
    db.close()


@pytest.mark.parametrize("kind", ["timeout", "missing_usage", "provider_failure"])
def test_uncertain_call_pauses_without_hidden_retry(kind) -> None:
    db, run, engine = _live()
    sent = []

    def handler(request):
        sent.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("sensitive network detail")
        return _response(usage=False) if kind == "missing_usage" else httpx.Response(503)

    gateway = _gateway(engine, run, handler)
    with pytest.raises(ModelGatewayError, match="usage_uncertain"):
        gateway.complete(GatewayRequest(messages=(), max_tokens=100))
    db.expire_all()
    assert run.status == "partial" and run.error_code == "evaluation.usage_uncertain"
    assert run.calls_reserved == 1 and run.calls_used == 0
    assert db.scalar(select(EvaluationModelCall.status)) == "usage_uncertain"
    with pytest.raises(ModelGatewayError, match="live_not_running"):
        gateway.complete(GatewayRequest(messages=()))
    assert len(sent) == 1
    db.close()


@pytest.mark.parametrize("limit", ["calls", "tokens", "time"])
def test_any_exhausted_limit_prevents_network(limit) -> None:
    db, run, engine = _live(max_calls=1, max_tokens=1000)
    if limit == "calls":
        reserve_call(engine, run.id, "previous", "a" * 64, 100)
    if limit == "time":
        run.started_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    sent = []
    gateway = _gateway(engine, run, lambda request: sent.append(request) or _response())
    with pytest.raises(ModelGatewayError, match="budget_exceeded"):
        gateway.complete(GatewayRequest(messages=(), max_tokens=2000 if limit == "tokens" else 100))
    assert sent == []
    db.close()


def test_structured_repair_is_a_separate_budgeted_call() -> None:
    db, run, engine = _live(max_calls=2)
    sent = []

    class Output(BaseModel):
        value: int

    def handler(request):
        sent.append(request)
        return _response('{"value":"invalid"}' if len(sent) == 1 else '{"value":1}')

    result = _gateway(engine, run, handler).generate_structured(
        GatewayRequest(messages=(), max_tokens=100), Output
    )
    assert result.output.value == 1
    assert result.usage.total_tokens == 60
    db.expire_all()
    assert run.calls_used == 2 and run.tokens_used == 60
    db.close()


def test_provider_overestimate_is_recorded_truthfully_and_stops_further_calls() -> None:
    db, run, engine = _live(max_tokens=1000)
    receipt = reserve_call(engine, run.id, "case-1:0", "a" * 64, 100)
    settle_call(engine, receipt, 1001)
    db.expire_all()
    assert run.tokens_used == 1001 and run.tokens_reserved == 0
    assert run.status == "partial" and run.error_code == "evaluation.budget_exceeded"
    db.close()


def test_streaming_cannot_bypass_budget() -> None:
    db, run, engine = _live()
    gateway = _gateway(engine, run, lambda request: _response())
    with pytest.raises(ModelGatewayError, match="streaming_not_enabled"):
        gateway.stream(GatewayRequest(messages=()))
    assert run.calls_used == run.calls_reserved == 0
    db.close()


def test_dispatch_crash_keeps_reservation_and_cannot_auto_retry() -> None:
    db, run, engine = _live()
    receipt = reserve_call(engine, run.id, "crashed", "a" * 64, 100)
    assert recover_uncertain_calls(engine) == 0
    assert recover_uncertain_calls(engine, now=datetime.now(UTC) + timedelta(minutes=6)) == 1
    db.expire_all()
    assert run.status == "partial" and run.calls_reserved == 1 and run.tokens_reserved == 100
    call = db.get(EvaluationModelCall, receipt)
    assert call is not None and call.status == "usage_uncertain"
    assert recover_uncertain_calls(engine, now=datetime.now(UTC) + timedelta(minutes=6)) == 0
    db.close()


def test_frozen_model_mismatch_prevents_network() -> None:
    db, run, engine = _live()
    sent = []
    gateway = BudgetedDeepSeekGateway(
        engine=engine,
        run_id=run.id,
        call_prefix="case-1",
        api_key="synthetic-not-a-secret",
        model="unapproved-model",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: sent.append(request) or _response())
        ),
    )
    with pytest.raises(ModelGatewayError, match="model_changed"):
        gateway.complete(GatewayRequest(messages=()))
    assert sent == []
    db.close()


def test_late_provider_response_after_watchdog_pause_is_not_published() -> None:
    db, run, engine = _live()

    def handler(_request):
        receipt_id = db.scalar(select(EvaluationModelCall.id))
        assert receipt_id is not None
        assert settle_call(engine, receipt_id, None)
        return _response()

    gateway = _gateway(engine, run, handler)
    with pytest.raises(ModelGatewayError, match="usage_uncertain"):
        gateway.complete(GatewayRequest(messages=(), max_tokens=100))
    db.expire_all()
    assert run.status == "partial" and run.calls_used == 0
    db.close()
