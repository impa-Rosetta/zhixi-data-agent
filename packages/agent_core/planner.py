"""Deterministic semantic binding around model-produced intent candidates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.agent_core.contracts import AnalysisPlan, AnalysisStep, Binding, Intent
from packages.model_gateway import GatewayMessage, GatewayRequest, GatewayUsage, ModelGateway
from packages.shared_contracts.semantic_models import SemanticDocument


class SemanticBindingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PublishedSemantic:
    model_id: str
    version_id: str
    document: SemanticDocument


def understand(
    gateway: ModelGateway,
    question: str,
    *,
    context: dict[str, object] | None = None,
) -> tuple[Intent, GatewayUsage]:
    prompt = (
        "Extract a manufacturing quality analysis intent as JSON. "
        "Use metric and dimension terms from the user; never invent formulas, SQL, code, "
        "credentials or authorization. Include domain, task_type, goal, metrics, dimensions, "
        "filters, time_range, comparison, output, ambiguities and confidence. "
        f"Prior structured context: {context or {}}. User question: {question}"
    )
    result = gateway.generate_structured(
        GatewayRequest(
            messages=(GatewayMessage(role="user", content=prompt),),
            thinking=False,
            max_tokens=1200,
        ),
        Intent,
    )
    return Intent.model_validate(result.output), result.usage


def bind_intent(
    intent: Intent,
    semantics: tuple[PublishedSemantic, ...],
    *,
    confidence_threshold: float = 0.72,
) -> Binding:
    if intent.confidence < confidence_threshold or intent.ambiguities or not intent.metrics:
        raise SemanticBindingError(
            "agent.clarification_required", "The question needs a metric clarification"
        )
    candidates: list[tuple[PublishedSemantic, tuple[str, ...], tuple[str, ...]]] = []
    for semantic in semantics:
        metrics = _resolve_terms(
            intent.metrics,
            ((item.key, item.name, tuple(item.aliases)) for item in semantic.document.metrics),
        )
        dimensions = _resolve_terms(
            intent.dimensions,
            ((item.key, item.name, tuple(item.aliases)) for item in semantic.document.dimensions),
        )
        if metrics is not None and dimensions is not None:
            candidates.append((semantic, metrics, dimensions))
    if len(candidates) != 1:
        raise SemanticBindingError(
            "agent.clarification_required",
            "Metric or dimension does not resolve uniquely in one published semantic model",
        )
    semantic, metrics, dimensions = candidates[0]
    snapshots = tuple(sorted({str(mapping.snapshot_id) for mapping in semantic.document.mappings}))
    return Binding(
        semantic_model_id=semantic.model_id,
        semantic_version_id=semantic.version_id,
        snapshot_ids=snapshots,
        metric_keys=metrics,
        dimension_keys=dimensions,
        confidence=intent.confidence,
    )


def _resolve_terms(
    requested: tuple[str, ...],
    definitions: Iterable[tuple[str, str, tuple[str, ...]]],
) -> tuple[str, ...] | None:
    items = tuple(definitions)
    resolved: list[str] = []
    for term in requested:
        normalized = term.strip().casefold()
        matches = [
            key
            for key, name, aliases in items
            if normalized in {key.casefold(), name.casefold(), *(a.casefold() for a in aliases)}
        ]
        if len(matches) != 1:
            return None
        resolved.append(matches[0])
    return tuple(resolved)


def create_plan(intent: Intent, binding: Binding) -> AnalysisPlan:
    arguments: dict[str, object] = {
        "semantic_model_id": binding.semantic_model_id,
        "semantic_version_id": binding.semantic_version_id,
        "metrics": list(binding.metric_keys),
        "dimensions": list(binding.dimension_keys),
        "filters": dict(intent.filters),
        "time_range": intent.time_range,
        "comparison": intent.comparison or "none",
        "limit": 200,
    }
    return AnalysisPlan(
        goal=intent.goal,
        steps=(
            AnalysisStep(
                id="trusted_metric_query",
                tool="query.metric",
                arguments=arguments,
                expected_evidence=("validated_query", "query_execution"),
            ),
        ),
        requires_confirmation=False,
    )
