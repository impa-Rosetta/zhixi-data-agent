"""Projection of completed runs into the bounded, reusable conversation context."""

from __future__ import annotations

import uuid

from pydantic import ValidationError

from packages.agent_core.contracts import Binding, Intent
from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisDimensionContext,
    AnalysisFilterContext,
    AnalysisMetricContext,
    AnalysisResultContext,
    ComparisonMode,
    ResultShape,
    TimeGrain,
    TurnRelation,
)


def _time_grain(intent: Intent) -> TimeGrain | None:
    text = "".join((intent.goal, intent.time_range or "", *intent.dimensions)).casefold()
    for markers, value in (
        (("按天", "每日", "天粒度"), "day"),
        (("按周", "每周", "周粒度"), "week"),
        (("按月", "每月", "月度", "月粒度"), "month"),
        (("按季度", "季度", "季粒度"), "quarter"),
        (("按年", "每年", "年度", "年粒度"), "year"),
    ):
        if any(marker in text for marker in markers):
            return value  # type: ignore[return-value]
    return None


def _comparison(value: str | None) -> ComparisonMode | None:
    if value is None:
        return None
    normalized = value.casefold()
    if any(marker in normalized for marker in ("同比", "previous_year", "year_over_year")):
        return "previous_year"
    if any(
        marker in normalized
        for marker in ("环比", "上月", "上周", "上一期", "previous_period")
    ):
        return "previous_period"
    if any(marker in normalized for marker in ("基线", "baseline")):
        return "baseline"
    return None


def _filters(intent: Intent) -> list[AnalysisFilterContext]:
    projected: list[AnalysisFilterContext] = []
    for field_key, value in list(intent.filters.items())[:20]:
        try:
            projected.append(
                AnalysisFilterContext(field_key=field_key, operator="eq", value=value)
            )
        except ValidationError:
            continue
    return projected


def _shape(intent: Intent, artifact_type: str, result: dict[str, object]) -> ResultShape:
    if artifact_type == "catalog_result":
        return "catalog"
    if intent.task_type == "comparison":
        return "comparison"
    if intent.task_type == "ranking":
        return "ranking"
    if intent.task_type == "trend" or "time_series" in intent.output:
        return "time_series"
    rows = result.get("rows")
    if (
        isinstance(rows, list)
        and len(rows) == 1
        and isinstance(rows[0], list)
        and len(rows[0]) == 1
    ):
        return "scalar"
    return "table"


def _result_context(
    *,
    intent: Intent,
    artifact_id: uuid.UUID,
    evidence_id: uuid.UUID | None,
    artifact_type: str,
    result: dict[str, object],
) -> AnalysisResultContext:
    rows = result.get("rows")
    safe_rows = rows if isinstance(rows, list) else []
    raw_count = result.get("row_count")
    row_count = raw_count if isinstance(raw_count, int) and raw_count >= 0 else len(safe_rows)
    primary_value: str | None = None
    if (
        len(safe_rows) == 1
        and isinstance(safe_rows[0], list)
        and len(safe_rows[0]) == 1
    ):
        primary_value = str(safe_rows[0][0])[:200]
    return AnalysisResultContext(
        artifact_id=artifact_id,
        evidence_id=evidence_id,
        shape=_shape(intent, artifact_type, result),
        row_count=min(row_count, 1_000_000),
        primary_value=primary_value,
    )


def project_completed_run_context(
    *,
    intent: Intent,
    binding: Binding | None,
    relation: TurnRelation,
    artifact_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
    artifact_type: str = "query_result",
    result: dict[str, object] | None = None,
    result_is_validated: bool = False,
) -> AnalysisConversationContext:
    """Keep only strict business context and verified result references."""
    metric: AnalysisMetricContext | None = None
    dimensions: list[AnalysisDimensionContext] = []
    if binding is not None and binding.metric_keys and intent.metrics:
        try:
            metric = AnalysisMetricContext(key=binding.metric_keys[0], name=intent.metrics[0])
        except ValidationError:
            metric = None
    if binding is not None:
        for index, key in enumerate(binding.dimension_keys[:10]):
            name = intent.dimensions[index] if index < len(intent.dimensions) else key
            try:
                dimensions.append(AnalysisDimensionContext(key=key, name=name))
            except ValidationError:
                continue
    last_result = None
    if result_is_validated and artifact_id is not None and result is not None:
        last_result = _result_context(
            intent=intent,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            artifact_type=artifact_type,
            result=result,
        )
    return AnalysisConversationContext(
        topic_summary=intent.goal[:500],
        metric=metric,
        dimensions=dimensions,
        time_grain=_time_grain(intent),
        filters=_filters(intent),
        comparison=_comparison(intent.comparison),
        last_result=last_result,
        last_relation=relation,
    )
