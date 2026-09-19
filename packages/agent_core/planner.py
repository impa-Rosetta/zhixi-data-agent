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
    ContextPatch,
    Intent,
    IntentRevision,
    RouteDecision,
)
from packages.agent_core.small_talk import classify_small_talk
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


_CAPABILITY_QUESTION_MARKERS = (
    "你是谁",
    "你是什么",
    "什么agent",
    "能做什么",
    "有什么功能",
    "支持什么",
    "功能介绍",
    "介绍一下你",
    "whatcanyoudo",
    "howcanyouhelp",
    "whatareyou",
)


def _direct_capability_intent(question: str) -> Intent | None:
    normalized = "".join(question.casefold().split())
    if not any(marker in normalized for marker in _CAPABILITY_QUESTION_MARKERS):
        return None
    return Intent(
        task_type="capability_help",
        goal=question.strip(),
        confidence=1.0,
    )


def _direct_small_talk_intent(question: str) -> Intent | None:
    if classify_small_talk(question) is None:
        return None
    return Intent(task_type="small_talk", goal=question.strip(), confidence=1.0)


def understand(
    gateway: ModelGateway,
    question: str,
    *,
    context: dict[str, object] | None = None,
) -> tuple[Intent, GatewayUsage]:
    direct_small_talk = _direct_small_talk_intent(question)
    if direct_small_talk is not None:
        return direct_small_talk, GatewayUsage(model_calls=0)
    direct_intent = _direct_capability_intent(question)
    if direct_intent is not None:
        return direct_intent, GatewayUsage(model_calls=0)
    prompt = (
        "Extract a manufacturing quality analysis intent as JSON. "
        "Classify short social greetings or thanks as small_talk, capability questions as "
        "capability_help, questions about available data, "
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
    *,
    relation: str | None = None,
    suggested_patch: dict[str, object] | None = None,
) -> tuple[Intent, IntentRevision, GatewayUsage]:
    prompt = (
        "Revise the prior manufacturing analysis intent using the new user message. "
        "Return mode=patch with only structured ContextPatch fields when the user is adding "
        "metrics, dimensions, filters, time_range, comparison or output. Return mode=replace "
        "with a complete Intent only when the user explicitly changes the task goal. "
        "Never add formulas, SQL, code, credentials or authorization. "
        f"Validated follow-up relation: {relation}. "
        f"Deterministic safe patch candidate: {suggested_patch}. "
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
    revised = revision.apply(previous)
    if suggested_patch:
        revised = ContextPatch.model_validate(suggested_patch).apply(revised)
    return revised, revision, result.usage


def route_intent(intent: Intent) -> RouteDecision:
    if intent.task_type == "small_talk":
        return RouteDecision(route="small_talk", requires_binding=False)
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
        defaults["dimensions"] = "time" if route == "trend" else "aggregate"
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
        dimensions = _resolve_dimensions(
            intent.dimensions,
            semantic.document,
            metrics or (),
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
    metric_definitions = {item.key: item for item in semantic.document.metrics}
    supported_sets = [
        set(metric_definitions[key].supported_dimensions)
        for key in metrics
        if key in metric_definitions
    ]
    supported = set.intersection(*supported_sets) if supported_sets else set()
    temporal_dimensions = [
        item.key
        for item in semantic.document.dimensions
        if item.dimension_type == "temporal" and item.key in supported
    ]
    time_dimension = temporal_dimensions[0] if len(temporal_dimensions) == 1 else None
    effective_dimensions = dimensions
    if intent.task_type == "trend" and not effective_dimensions and time_dimension is not None:
        effective_dimensions = (time_dimension,)
    snapshots = tuple(sorted({str(mapping.snapshot_id) for mapping in semantic.document.mappings}))
    return Binding(
        semantic_model_id=semantic.model_id,
        semantic_version_id=semantic.version_id,
        snapshot_ids=snapshots,
        metric_keys=metrics,
        dimension_keys=effective_dimensions,
        time_dimension_key=time_dimension,
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


_TIME_GRAIN_TERMS = {
    "小时": "hour",
    "按小时": "hour",
    "日期": "day",
    "天": "day",
    "按天": "day",
    "周": "week",
    "按周": "week",
    "月份": "month",
    "月": "month",
    "按月": "month",
    "季度": "quarter",
    "按季度": "quarter",
    "年份": "year",
    "年": "year",
    "按年": "year",
}


def _resolve_dimensions(
    requested: tuple[str, ...],
    document: SemanticDocument,
    metric_keys: tuple[str, ...],
) -> tuple[str, ...] | None:
    metrics = {item.key: item for item in document.metrics}
    supported_sets = [
        set(metrics[key].supported_dimensions) for key in metric_keys if key in metrics
    ]
    supported = set.intersection(*supported_sets) if supported_sets else set()
    resolved: list[str] = []
    for term in requested:
        normalized = term.strip().casefold()
        if normalized in _TIME_GRAIN_TERMS:
            matches = [
                item.key
                for item in document.dimensions
                if item.dimension_type == "temporal" and item.key in supported
            ]
        else:
            matches = [
                item.key
                for item in document.dimensions
                if normalized
                in {
                    item.key.casefold(),
                    item.name.casefold(),
                    *(alias.casefold() for alias in item.aliases),
                }
            ]
        if len(matches) != 1:
            return None
        resolved.append(matches[0])
    return tuple(resolved)


def _intent_time_grain(intent: Intent) -> str | None:
    text = "".join((intent.goal, intent.time_range or "", *intent.dimensions)).casefold()
    for markers, grain in (
        (("小时", "按小时"), "hour"),
        (("按天", "每日", "日期", "天粒度"), "day"),
        (("按周", "每周", "上周", "周粒度"), "week"),
        (("按月", "每月", "月份", "本月", "上月", "月度", "月粒度"), "month"),
        (("按季度", "季度", "季粒度"), "quarter"),
        (("按年", "每年", "年份", "去年", "年度", "年粒度"), "year"),
    ):
        if any(marker in text for marker in markers):
            return grain
    return None


def create_plan(intent: Intent, binding: Binding) -> AnalysisPlan:
    time_grain = _intent_time_grain(intent)
    if time_grain is None and intent.task_type == "trend" and binding.dimension_keys:
        time_grain = "month"
    arguments: dict[str, object] = {
        "semantic_model_id": binding.semantic_model_id,
        "semantic_version_id": binding.semantic_version_id,
        "metrics": list(binding.metric_keys),
        "dimensions": list(binding.dimension_keys),
        "filters": dict(intent.filters),
        "time_range": intent.time_range,
        "time_dimension": binding.time_dimension_key,
        "comparison": intent.comparison or "none",
        "time_grain": time_grain if binding.dimension_keys else None,
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
            AnalysisStep(
                id="describe_result",
                tool="analysis.describe",
                arguments={"artifact_id": "$trusted_metric_query.artifact"},
                depends_on=("trusted_metric_query",),
                expected_evidence=("descriptive_statistics",),
            ),
            AnalysisStep(
                id="compose_visualization",
                tool="visualization.compose",
                arguments={"artifact_id": "$trusted_metric_query.artifact"},
                depends_on=("trusted_metric_query",),
                expected_evidence=("chart_spec",),
            ),
        ),
        requires_confirmation=False,
    )
