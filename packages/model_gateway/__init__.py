"""Provider-independent model gateway with a DeepSeek adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class GatewayToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class GatewayMessage:
    role: MessageRole
    content: str | None
    name: str | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[GatewayToolCall, ...] = ()


@dataclass(frozen=True)
class GatewayTool:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class GatewayRequest:
    messages: tuple[GatewayMessage, ...]
    tools: tuple[GatewayTool, ...] = ()
    thinking: bool = False
    reasoning_effort: Literal["low", "high", "max"] = "high"
    max_tokens: int = 2048
    response_format: Literal["text", "json_object"] = "text"
    user_id: str | None = None


@dataclass(frozen=True)
class GatewayUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class GatewayResponse:
    request_id: str
    model: str
    content: str | None
    reasoning_content: str | None
    tool_calls: tuple[GatewayToolCall, ...]
    finish_reason: str
    usage: GatewayUsage


@dataclass(frozen=True)
class StructuredGatewayResponse:
    output: BaseModel
    response: GatewayResponse

    @property
    def usage(self) -> GatewayUsage:
        return self.response.usage

    @property
    def reasoning_content(self) -> str | None:
        return self.response.reasoning_content


@dataclass(frozen=True)
class GatewayStreamEvent:
    event_type: Literal["content", "reasoning", "usage", "done"]
    text: str = ""
    usage: GatewayUsage | None = None


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ModelGateway(Protocol):
    def complete(self, request: GatewayRequest) -> GatewayResponse: ...

    def generate_structured(
        self, request: GatewayRequest, schema: type[T]
    ) -> StructuredGatewayResponse: ...


class DeepSeekGateway:
    """Official-protocol adapter whose errors never contain credentials."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-pro",
        timeout_seconds: float = 45.0,
        max_attempts: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ModelGatewayError("model.not_configured")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_attempts = max(1, min(max_attempts, 5))
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=self._payload(request),
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 < self._max_attempts:
                    time.sleep(min(0.25 * (2**attempt), 1.0))
                    continue
                raise ModelGatewayError("model.network_error", retryable=True) from exc
            if response.status_code >= 400:
                error = self._http_error(response.status_code)
                if error.retryable and attempt + 1 < self._max_attempts:
                    time.sleep(min(0.25 * (2**attempt), 1.0))
                    continue
                raise error
            try:
                return self._parse_response(response.json())
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ModelGatewayError("model.invalid_response") from exc
        raise ModelGatewayError("model.retry_exhausted", retryable=True)

    def generate_structured(
        self, request: GatewayRequest, schema: type[T]
    ) -> StructuredGatewayResponse:
        messages = request.messages
        if not any("JSON" in (message.content or "") for message in messages):
            messages = (
                GatewayMessage(
                    role="system",
                    content="Return one valid JSON object matching the requested schema.",
                ),
                *messages,
            )
        response = self.complete(
            GatewayRequest(
                messages=messages,
                tools=request.tools,
                thinking=request.thinking,
                reasoning_effort=request.reasoning_effort,
                max_tokens=request.max_tokens,
                response_format="json_object",
                user_id=request.user_id,
            )
        )
        if response.content is None:
            raise ModelGatewayError("model.missing_structured_output")
        try:
            output = schema.model_validate_json(response.content)
        except ValidationError as exc:
            raise ModelGatewayError("model.schema_validation_failed") from exc
        return StructuredGatewayResponse(output=output, response=response)

    def stream(self, request: GatewayRequest) -> Iterator[GatewayStreamEvent]:
        payload = self._payload(request)
        payload.update({"stream": True, "stream_options": {"include_usage": True}})
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    raise self._http_error(response.status_code)
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        yield GatewayStreamEvent("done")
                        return
                    data = json.loads(raw)
                    usage = data.get("usage")
                    if isinstance(usage, dict):
                        yield GatewayStreamEvent("usage", usage=self._usage(usage))
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield GatewayStreamEvent("reasoning", text=delta["reasoning_content"])
                    if delta.get("content"):
                        yield GatewayStreamEvent("content", text=delta["content"])
        except ModelGatewayError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelGatewayError("model.stream_failed", retryable=True) from exc

    def _payload(self, request: GatewayRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [self._message(message) for message in request.messages],
            "max_tokens": request.max_tokens,
            "thinking": {"type": "enabled" if request.thinking else "disabled"},
        }
        if request.thinking:
            payload["reasoning_effort"] = request.reasoning_effort
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        if request.user_id:
            payload["user_id"] = request.user_id
        return payload

    @staticmethod
    def _message(message: GatewayMessage) -> dict[str, object]:
        item: dict[str, object] = {"role": message.role, "content": message.content}
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.reasoning_content:
            item["reasoning_content"] = message.reasoning_content
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return item

    def _parse_response(self, data: dict[str, object]) -> GatewayResponse:
        choices = data["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError("missing choices")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("missing message")
        message = choice["message"]
        calls: list[GatewayToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            calls.append(GatewayToolCall(str(item["id"]), str(function["name"]), arguments))
        usage = data.get("usage")
        return GatewayResponse(
            request_id=str(data.get("id", "")),
            model=str(data.get("model", self._model)),
            content=message.get("content") if isinstance(message.get("content"), str) else None,
            reasoning_content=(
                message.get("reasoning_content")
                if isinstance(message.get("reasoning_content"), str)
                else None
            ),
            tool_calls=tuple(calls),
            finish_reason=str(choice.get("finish_reason", "stop")),
            usage=self._usage(usage if isinstance(usage, dict) else {}),
        )

    @staticmethod
    def _usage(value: dict[str, object]) -> GatewayUsage:
        return GatewayUsage(
            prompt_tokens=_integer(value.get("prompt_tokens")),
            completion_tokens=_integer(value.get("completion_tokens")),
            total_tokens=_integer(value.get("total_tokens")),
        )

    @staticmethod
    def _http_error(status_code: int) -> ModelGatewayError:
        if status_code in {401, 403}:
            return ModelGatewayError("model.authentication_failed")
        if status_code == 429:
            return ModelGatewayError("model.rate_limited", retryable=True)
        if status_code in {408, 409} or status_code >= 500:
            return ModelGatewayError("model.provider_unavailable", retryable=True)
        return ModelGatewayError("model.request_rejected")


@dataclass
class FakeGateway:
    """Deterministic protocol fake; never used as a production fallback."""

    responses: list[GatewayResponse] = field(default_factory=list)
    calls: list[GatewayRequest] = field(default_factory=list)

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        self.calls.append(request)
        if not self.responses:
            raise ModelGatewayError("model.fake_exhausted")
        return self.responses.pop(0)

    def generate_structured(
        self, request: GatewayRequest, schema: type[T]
    ) -> StructuredGatewayResponse:
        response = self.complete(request)
        if response.content is None:
            raise ModelGatewayError("model.missing_structured_output")
        try:
            output = schema.model_validate_json(response.content)
        except ValidationError as exc:
            raise ModelGatewayError("model.schema_validation_failed") from exc
        return StructuredGatewayResponse(output=output, response=response)


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


__all__ = [
    "DeepSeekGateway",
    "FakeGateway",
    "GatewayMessage",
    "GatewayRequest",
    "GatewayResponse",
    "GatewayStreamEvent",
    "GatewayTool",
    "GatewayToolCall",
    "GatewayUsage",
    "ModelGateway",
    "ModelGatewayError",
    "StructuredGatewayResponse",
]
