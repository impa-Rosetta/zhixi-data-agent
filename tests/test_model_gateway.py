import json

import httpx
import pytest
from pydantic import BaseModel

from packages.model_gateway import (
    DeepSeekGateway,
    GatewayMessage,
    GatewayRequest,
    ModelGatewayError,
)


class IntentPayload(BaseModel):
    task_type: str
    confidence: float


def test_deepseek_gateway_uses_official_protocol_and_validates_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-pro"
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        assert "JSON Schema" in body["messages"][0]["content"]
        assert "task_type" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "id": "call-1",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"task_type":"metric_query","confidence":0.98}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
            },
        )

    gateway = DeepSeekGateway(
        api_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=1,
    )
    result = gateway.generate_structured(
        GatewayRequest(messages=(GatewayMessage(role="user", content="分析不良率"),)),
        IntentPayload,
    )
    assert result.output.task_type == "metric_query"
    assert result.usage.total_tokens == 19
    assert result.reasoning_content is None


def test_deepseek_gateway_repairs_one_invalid_structured_response() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        content = (
            '{"task_type":"metric_query"}'
            if len(calls) == 1
            else '{"task_type":"metric_query","confidence":0.97}'
        )
        return httpx.Response(
            200,
            json={
                "id": f"call-{len(calls)}",
                "model": "deepseek-v4-pro",
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    gateway = DeepSeekGateway(
        api_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=1,
    )
    result = gateway.generate_structured(
        GatewayRequest(messages=(GatewayMessage(role="user", content="分析不良率"),)),
        IntentPayload,
    )

    assert result.output.confidence == 0.97
    assert len(calls) == 2
    assert "did not validate" in calls[1]["messages"][-1]["content"]
    assert result.usage.total_tokens == 30
    assert result.usage.model_calls == 2


def test_gateway_maps_auth_failure_without_leaking_secret() -> None:
    gateway = DeepSeekGateway(
        api_key="never-print-this",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))),
        max_attempts=1,
    )
    with pytest.raises(ModelGatewayError, match="model.authentication_failed") as error:
        gateway.complete(GatewayRequest(messages=(GatewayMessage(role="user", content="hi"),)))
    assert "never-print-this" not in str(error.value)
