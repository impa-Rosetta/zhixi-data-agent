"""Deterministic semantic binding around model-produced intent candidates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.agent_core.contracts import (
    AnalysisPlan,
    AnalysisRoute,
    AnalysisStep,
    Binding,
    ClarificationCandidate,
    ClarificationRequest,
    Intent,
    IntentRevision,
    RouteDecision,
)
from packages.model_gateway import GatewayMessage, GatewayRequest, GatewayUsage, ModelGateway
from packages.shared_contracts.semantic_models import SemanticDocument


class SemanticBindingError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        clarification: ClarificationRequest,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.clarification = clarification


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
        "Classify capability questions as capability_help, questions about available data, "
        "tables or fields as catalog_exploration, governed metric questions as metric_query, "
        "and unrelated or prohibited requests as unsupported. "
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


def revise_intent(
    gateway: ModelGateway,
    previous: Intent,
    message: str,
) -> tuple[Intent, IntentRevision, GatewayUsage]:
    prompt = (
        "Revise the prior manufacturing analysis intent using the new user message. "
        "Return mode=patch with only structured ContextPatch fields when the user is adding "
        "metrics, dimensions, filters, time_range, comparison or output. Return mode=replace "
        "with a complete Intent only when the user explicitly changes the task goal. "
        "Never add formulas, SQL, code, credentials or authorization. "
        f"Prior intent: {previous.model_dump(mode='json')}. New user message: {message}"
    )
    result = gateway.generate_structured(
        GatewayRequest(
            messages=(GatewayMessage(role="user", content=prompt),),
            thinking=False,
            max_tokens=1200,
        ),
        IntentRevision,
    )
    revision = IntentRevision.model_validate(result.output)
    return revision.apply(previous), revision, result.usage


def route_intent(intent: Intent) -> RouteDecision:
    if intent.task_type == "capability_help":
        return RouteDecision(route="capability_help", requires_binding=False)
    if intent.task_type in {"catalog_exploration", "exploration"}:
        return RouteDecision(route="catalog_exploration", requires_binding=False)
    if intent.task_type in {"unsupported", "clarification"}:
        return RouteDecision(route="unsupported", requires_binding=False)

    route: AnalysisRoute
    if intent.task_type == "metric_query":
        route = "metric_query"
    elif intent.task_type == "comparison":
        route = "comparison"
    elif intent.task_type == "ranking":
        route = "ranking"
    elif intent.task_type == "trend":
        route = "trend"
    else:
        return RouteDecision(route="unsupported", requires_binding=False)
    if not intent.metrics:
        return RouteDecision(
            route=route,
            requires_binding=True,
            clarification=_metric_required(),
        )
    if route == "comparison" and (intent.time_range is None or intent.comparison is None):
        return RouteDecision(
            route=route,
            requires_binding=True,
            clarification=ClarificationRequest(
                reason_code="comparison_period_required",
                question="请说明要比较的当前周期和对比周期。",
                missing_fields=tuple(
                    field
                    for field, value in (
                        ("time_range", intent.time_range),
                        ("comparison", intent.comparison),
                    )
                    if value is None
                ),
                suggested_answers=("本月与上月", "本季度与上季度", "今年与去年"),
                resume_node="route",
            ),
        )
    defaults: dict[str, str] = {}
    if intent.time_range is None:
        defaults["time_range"] = "all_available"
    if not intent.dimensions:
        defaults["dimensions"] = "aggregate"
    return RouteDecision(
        route=route,
        requires_binding=True,
        defaults_applied=defaults,
    )


def bind_intent(
    intent: Intent,
    semantics: tuple[PublishedSemantic, ...],
    *,
    confidence_threshold: float = 0.72,
) -> Binding:
    del confidence_threshold  # Confidence is observable; deterministic resolution is authoritative.
    if not intent.metrics:
        raise SemanticBindingError(
            "agent.clarification_required",
            "The question needs a metric clarification",
            _metric_required(),
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
        metric_label = "、".join(intent.metrics)
        reason_code = (
            "semantic_binding_ambiguous" if len(candidates) > 1 else "semantic_binding_not_found"
        )
        candidate_items = tuple(
            ClarificationCandidate(
                key=semantic.model_id,
                label=f"{metric_label} · 语义模型 {semantic.model_id}",
                description=f"已发布版本 {semantic.version_id}",
            )
            for semantic, _, _ in candidates[:20]
        )
        if candidate_items:
            question = f"“{metric_label}”对应多个已发布口径，请选择一个。"
        else:
            question = f"找不到“{metric_label}”的唯一已发布口径，请更换指标或检查语义模型。"
        raise SemanticBindingError(
            "agent.clarification_required",
            "Metric or dimension does not resolve uniquely in one published semantic model",
            ClarificationRequest(
                reason_code=reason_code,
                question=question,
                missing_fields=() if candidate_items else ("metrics",),
                candidates=candidate_items,
                suggested_answers=tuple(item.label for item in candidate_items[:3]),
                resume_node="bind",
            ),
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


def _metric_required() -> ClarificationRequest:
    return ClarificationRequest(
        reason_code="metric_required",
        question="你希望分析哪个指标？",
        missing_fields=("metrics",),
        suggested_answers=("分析不良率", "分析一次通过率", "分析返工率"),
        resume_node="understand",
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
