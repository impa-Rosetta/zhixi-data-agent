"""Protocol and failure tests that never contact a model provider."""

import json

import httpx
import pytest
from pydantic import BaseModel

from packages.model_gateway import (
    DeepSeekGateway,
    GatewayMessage,
    GatewayRequest,
    GatewayTool,
    GatewayToolCall,
    ModelGatewayError,
)


class _Answer(BaseModel):
    value: int


def _gateway(handler, *, attempts=1):
    return DeepSeekGateway(
        api_key="synthetic-test-only",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=attempts,
    )


def _reply(content='{"value":7}', *, tool_calls=None):
    return httpx.Response(
        200,
        json={
            "id": "synthetic-call",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": content, "tool_calls": tool_calls or []},
                }
            ],
        },
    )


def test_thinking_tool_payload_and_valid_tool_response() -> None:
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _reply(
            None,
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "query.metric", "arguments": '{"metric":"defect_rate"}'},
                }
            ],
        )

    gateway = _gateway(handler)
    response = gateway.complete(
        GatewayRequest(
            messages=(
                GatewayMessage(
                    role="assistant",
                    content=None,
                    reasoning_content="synthetic reasoning",
                    tool_calls=(GatewayToolCall("prior", "query.metric", {"metric": "a"}),),
                ),
                GatewayMessage(role="tool", content="{}", tool_call_id="prior"),
            ),
            tools=(GatewayTool("query.metric", "query", {"type": "object"}),),
            thinking=True,
            user_id="synthetic-user",
        )
    )
    assert seen[0]["thinking"] == {"type": "enabled"}
    assert seen[0]["reasoning_effort"] == "high"
    assert seen[0]["tool_choice"] == "auto"
    assert seen[0]["messages"][0]["reasoning_content"] == "synthetic reasoning"
    assert seen[0]["messages"][1]["tool_call_id"] == "prior"
    assert seen[0]["user_id"] == "synthetic-user"
    assert response.tool_calls == (
        GatewayToolCall("call-1", "query.metric", {"metric": "defect_rate"}),
    )


@pytest.mark.parametrize("arguments", ["[1,2]", "not json"])
def test_non_object_tool_arguments_fail_closed(arguments) -> None:
    gateway = _gateway(
        lambda _: _reply(
            None,
            tool_calls=[{"id": "x", "function": {"name": "query.metric", "arguments": arguments}}],
        )
    )
    with pytest.raises(ModelGatewayError, match="model.invalid_response"):
        gateway.complete(GatewayRequest(messages=(GatewayMessage(role="user", content="test"),)))


def test_rate_limit_retries_once_without_exposing_provider_body(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("packages.model_gateway.time.sleep", lambda *_: None)

    def handler(_request):
        calls.append(1)
        return (
            httpx.Response(429, text="synthetic provider secret") if len(calls) == 1 else _reply()
        )

    result = _gateway(handler, attempts=2).complete(
        GatewayRequest(messages=(GatewayMessage(role="user", content="test"),))
    )
    assert result.content == '{"value":7}' and len(calls) == 2


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "model.request_rejected", False),
        (429, "model.rate_limited", True),
        (503, "model.provider_unavailable", True),
    ],
)
def test_provider_failures_have_stable_safe_codes(status, code, retryable) -> None:
    gateway = _gateway(lambda _: httpx.Response(status, text="synthetic provider secret"))
    with pytest.raises(ModelGatewayError) as caught:
        gateway.complete(GatewayRequest(messages=(GatewayMessage(role="user", content="test"),)))
    assert caught.value.code == code and caught.value.retryable is retryable
    assert "synthetic provider secret" not in str(caught.value)


def test_repeated_invalid_structured_output_stops_after_one_repair() -> None:
    calls = []

    def handler(_request):
        calls.append(1)
        return _reply('{"value":"bad"}')

    with pytest.raises(ModelGatewayError, match="model.schema_validation_failed"):
        _gateway(handler).generate_structured(
            GatewayRequest(messages=(GatewayMessage(role="user", content="test"),)), _Answer
        )
    assert len(calls) == 2


def test_stream_emits_reasoning_content_usage_and_done() -> None:
    stream = "\n".join(
        (
            'data: {"choices":[{"delta":{"reasoning_content":"think","content":"answer"}}]}',
            'data: {"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}',
            "data: [DONE]",
        )
    )
    gateway = _gateway(lambda _: httpx.Response(200, text=stream))
    events = list(
        gateway.stream(GatewayRequest(messages=(GatewayMessage(role="user", content="test"),)))
    )
    assert [event.event_type for event in events] == ["reasoning", "content", "usage", "done"]
    assert events[0].text == "think" and events[1].text == "answer"
    assert events[2].usage is not None and events[2].usage.total_tokens == 5
