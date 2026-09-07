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


def test_gateway_maps_auth_failure_without_leaking_secret() -> None:
    gateway = DeepSeekGateway(
        api_key="never-print-this",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))),
        max_attempts=1,
    )
    with pytest.raises(ModelGatewayError, match="model.authentication_failed") as error:
        gateway.complete(GatewayRequest(messages=(GatewayMessage(role="user", content="hi"),)))
    assert "never-print-this" not in str(error.value)

