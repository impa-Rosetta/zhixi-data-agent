"""Fail-closed live-call budget. No public live runner is enabled by this module."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.evaluation.persistence import EvaluationModelCall, EvaluationRun
from packages.model_gateway import (
    DeepSeekGateway,
    GatewayRequest,
    GatewayResponse,
    GatewayStreamEvent,
    ModelGatewayError,
)


def _limits(run: EvaluationRun) -> tuple[int, int, int]:
    values = [run.budget.get(key) for key in ("max_calls", "max_tokens", "max_seconds")]
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values):
        raise ModelGatewayError("evaluation.invalid_budget")
    return int(str(values[0])), int(str(values[1])), int(str(values[2]))


def reserve_call(
    engine: Engine,
    run_id: uuid.UUID,
    call_key: str,
    digest: str,
    tokens: int,
    *,
    model: str | None = None,
) -> uuid.UUID:
    if not call_key or len(call_key) > 100 or tokens <= 0:
        raise ModelGatewayError("evaluation.invalid_budget")
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        if run is None or run.track != "live" or run.status != "running":
            raise ModelGatewayError("evaluation.live_not_running")
        if model is not None and model != run.model_version:
            raise ModelGatewayError("evaluation.model_changed")
        existing = db.scalar(
            select(EvaluationModelCall.id).where(
                EvaluationModelCall.evaluation_run_id == run_id,
                EvaluationModelCall.call_key == call_key,
            )
        )
        if existing is not None:
            raise ModelGatewayError("evaluation.call_already_recorded")
        max_calls, max_tokens, max_seconds = _limits(run)
        started = run.started_at
        if started is None:
            raise ModelGatewayError("evaluation.invalid_budget")
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (datetime.now(UTC) - started).total_seconds() >= max_seconds:
            raise ModelGatewayError("evaluation.budget_exceeded")
        changed = db.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.track == "live",
                EvaluationRun.status == "running",
                EvaluationRun.calls_used + EvaluationRun.calls_reserved < max_calls,
                EvaluationRun.tokens_used + EvaluationRun.tokens_reserved + tokens <= max_tokens,
            )
            .values(
                calls_reserved=EvaluationRun.calls_reserved + 1,
                tokens_reserved=EvaluationRun.tokens_reserved + tokens,
            )
        )
        if getattr(changed, "rowcount", 0) != 1:
            raise ModelGatewayError("evaluation.budget_exceeded")
        receipt = EvaluationModelCall(
            workspace_id=run.workspace_id,
            evaluation_run_id=run_id,
            call_key=call_key,
            request_digest=digest,
            reserved_tokens=tokens,
        )
        db.add(receipt)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ModelGatewayError("evaluation.call_already_recorded") from exc
        return receipt.id


def settle_call(engine: Engine, receipt_id: uuid.UUID, actual_tokens: int | None) -> bool:
    if actual_tokens is not None and (
        not isinstance(actual_tokens, int) or isinstance(actual_tokens, bool) or actual_tokens < 0
    ):
        raise ModelGatewayError("evaluation.invalid_usage")
    with Session(engine) as db:
        receipt = db.get(EvaluationModelCall, receipt_id)
        if receipt is None:
            raise ModelGatewayError("evaluation.call_not_found")
        unknown = actual_tokens is None
        changed = db.execute(
            update(EvaluationModelCall)
            .where(
                EvaluationModelCall.id == receipt_id,
                EvaluationModelCall.status == "sent",
            )
            .values(
                status="usage_uncertain" if unknown else "settled",
                actual_tokens=actual_tokens,
                finished_at=datetime.now(UTC),
            )
        )
        if getattr(changed, "rowcount", 0) != 1:
            return False
        if unknown:
            db.execute(
                update(EvaluationRun)
                .where(
                    EvaluationRun.id == receipt.evaluation_run_id,
                    EvaluationRun.status == "running",
                )
                .values(
                    status="partial",
                    error_code="evaluation.usage_uncertain",
                    finished_at=datetime.now(UTC),
                )
            )
        else:
            db.execute(
                update(EvaluationRun)
                .where(
                    EvaluationRun.id == receipt.evaluation_run_id,
                )
                .values(
                    calls_reserved=EvaluationRun.calls_reserved - 1,
                    tokens_reserved=EvaluationRun.tokens_reserved - receipt.reserved_tokens,
                    calls_used=EvaluationRun.calls_used + 1,
                    tokens_used=EvaluationRun.tokens_used + actual_tokens,
                )
            )
            run = db.get(EvaluationRun, receipt.evaluation_run_id)
            assert run is not None
            _, max_tokens, _ = _limits(run)
            if run.tokens_used > max_tokens:
                db.execute(
                    update(EvaluationRun)
                    .where(
                        EvaluationRun.id == run.id,
                        EvaluationRun.status == "running",
                    )
                    .values(
                        status="partial",
                        error_code="evaluation.budget_exceeded",
                        finished_at=datetime.now(UTC),
                    )
                )
        db.commit()
        return True


def recover_uncertain_calls(engine: Engine, *, now: datetime | None = None) -> int:
    """Quarantine stale dispatch receipts; never refund or automatically resend them."""
    current = now or datetime.now(UTC)
    with Session(engine) as db:
        overdue = list(
            db.scalars(
                select(EvaluationModelCall.id)
                .where(
                    EvaluationModelCall.status == "sent",
                    EvaluationModelCall.created_at < current - timedelta(minutes=5),
                )
                .limit(100)
            )
        )
    recovered = 0
    for receipt_id in overdue:
        if settle_call(engine, receipt_id, None):
            recovered += 1
    return recovered


class BudgetedDeepSeekGateway(DeepSeekGateway):
    """No transport retries; every structured repair goes through a new reservation."""

    def __init__(
        self,
        *,
        engine: Engine,
        run_id: uuid.UUID,
        call_prefix: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, max_attempts=1, client=client)
        self._budget_engine = engine
        self._evaluation_run_id = run_id
        self._call_prefix = call_prefix
        self._call_number = 0

    def _parse_response(self, data: dict[str, object]) -> GatewayResponse:
        usage = data.get("usage")
        if not isinstance(usage, dict) or any(
            not isinstance(usage.get(key), int)
            or isinstance(usage.get(key), bool)
            or usage[key] < 0
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        ):
            raise ModelGatewayError("evaluation.usage_uncertain")
        if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
            raise ModelGatewayError("evaluation.usage_uncertain")
        return super()._parse_response(data)

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        if not self._api_key:
            raise ModelGatewayError("model.not_configured")
        if (
            not isinstance(request.max_tokens, int)
            or isinstance(request.max_tokens, bool)
            or request.max_tokens <= 0
        ):
            raise ModelGatewayError("evaluation.invalid_budget")
        payload = json.dumps(self._payload(request), ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        # Conservative local estimate, not a guarantee of the provider's tokenizer or cost.
        reserved = len(payload.encode("utf-8")) + request.max_tokens + 256
        receipt = reserve_call(
            self._budget_engine,
            self._evaluation_run_id,
            f"{self._call_prefix}:{self._call_number}",
            digest,
            reserved,
            model=self._model,
        )
        self._call_number += 1
        try:
            response = super().complete(request)
        except Exception:
            settle_call(self._budget_engine, receipt, None)
            raise ModelGatewayError("evaluation.usage_uncertain") from None
        if not settle_call(self._budget_engine, receipt, response.usage.total_tokens):
            raise ModelGatewayError("evaluation.usage_uncertain")
        return response

    def stream(self, request: GatewayRequest) -> Iterator[GatewayStreamEvent]:
        raise ModelGatewayError("evaluation.streaming_not_enabled")
