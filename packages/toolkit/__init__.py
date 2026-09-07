"""Versioned, policy-aware tool registry used by the Agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ToolHandler = Callable[[dict[str, object]], dict[str, object]]
Risk = Literal["low", "medium", "high"]


class ToolRegistryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    required_action: str
    risk: Risk
    timeout_seconds: int
    max_attempts: int
    idempotent: bool
    cacheable: bool
    evidence_types: tuple[str, ...]
    dialects: tuple[str, ...] = ("postgres", "mysql")


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler | None = None) -> None:
        if spec.name in self._specs:
            raise ToolRegistryError("tool.duplicate")
        self._specs[spec.name] = spec
        if handler is not None:
            self._handlers[spec.name] = handler

    def bind(self, name: str, handler: ToolHandler) -> None:
        self.get(name)
        self._handlers[name] = handler

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolRegistryError("tool.not_registered") from exc

    def list_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs[name] for name in sorted(self._specs))

    def invoke(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        spec = self.get(name)
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolRegistryError("tool.not_available")
        _validate_required(arguments, spec.input_schema)
        return handler(arguments)


def _validate_required(arguments: dict[str, object], schema: dict[str, object]) -> None:
    required = schema.get("required", [])
    if isinstance(required, list) and any(key not in arguments for key in required):
        raise ToolRegistryError("tool.invalid_arguments")


def _schema(*required: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in required},
        "required": list(required),
        "additionalProperties": False,
    }


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    definitions = (
        ("catalog.search", "Search the authorized frozen catalog", _schema("query"), "catalog"),
        (
            "semantic.resolve",
            "Resolve governed metrics and dimensions",
            _schema("query"),
            "semantic",
        ),
        (
            "query.metric",
            "Compile and execute a trusted metric query",
            _schema("semantic_model_id", "metrics"),
            "query",
        ),
        (
            "query.explore",
            "Validate and execute exploratory read-only SQL",
            _schema("draft"),
            "query",
        ),
        ("analysis.describe", "Describe verified data", _schema("artifact_id"), "analysis"),
        (
            "analysis.compare",
            "Compare verified periods or groups",
            _schema("artifact_id"),
            "analysis",
        ),
        ("analysis.rank", "Rank verified groups", _schema("artifact_id"), "analysis"),
        (
            "analysis.correlate",
            "Measure correlation with causal warning",
            _schema("artifact_id"),
            "analysis",
        ),
        (
            "analysis.detect_anomaly",
            "Detect anomalies in verified data",
            _schema("artifact_id"),
            "analysis",
        ),
        (
            "visualization.compose",
            "Create a constrained chart specification",
            _schema("artifact_id"),
            "visualization",
        ),
        ("report.compose", "Assemble a report from artifacts", _schema("artifact_id"), "report"),
        (
            "run.request_confirmation",
            "Pause and request user confirmation",
            _schema("question"),
            "confirmation",
        ),
    )
    for name, description, input_schema, evidence in definitions:
        registry.register(
            ToolSpec(
                name=name,
                version="1.0.0",
                description=description,
                input_schema=input_schema,
                output_schema={"type": "object"},
                required_action="analysis.run",
                risk="medium" if name in {"query.explore", "report.compose"} else "low",
                timeout_seconds=15 if name.startswith("query.") else 10,
                max_attempts=2 if name.startswith("query.") else 1,
                idempotent=True,
                cacheable=name != "run.request_confirmation",
                evidence_types=(evidence,),
            )
        )
    return registry


__all__ = [
    "ToolRegistry",
    "ToolRegistryError",
    "ToolSpec",
    "build_default_registry",
]
