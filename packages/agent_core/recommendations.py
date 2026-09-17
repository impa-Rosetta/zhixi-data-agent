"""Deterministic, capability-bounded follow-up recommendations."""

from packages.agent_core.persistence import AnalysisArtifact, AnalysisRunStatus
from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisSuggestedFollowUpResponse,
)


def recommend_follow_ups(
    *,
    context: AnalysisConversationContext,
    run_status: AnalysisRunStatus,
    artifacts: list[AnalysisArtifact],
) -> list[AnalysisSuggestedFollowUpResponse]:
    if run_status not in {
        AnalysisRunStatus.COMPLETED,
        AnalysisRunStatus.FAILED,
        AnalysisRunStatus.CANCELLED,
    }:
        return []

    artifact_types = {artifact.artifact_type for artifact in artifacts}
    suggestions: list[AnalysisSuggestedFollowUpResponse]
    if context.last_result is not None and context.metric is not None:
        metric = context.metric.name
        shape = context.last_result.shape
        if shape == "time_series":
            suggestions = [
                _item("result.peak", "找出最高点", "哪个时间段最高？", "result_shape"),
                _item("result.compare", "对比上一期", "与上月相比有什么变化？", "result_shape"),
                _item("result.explain", "解释变化", "为什么会出现这样的变化？", "evidence"),
            ]
        elif shape == "ranking":
            suggestions = [
                _item(
                    "result.top-trend",
                    "查看头部趋势",
                    "第一名最近三个月的趋势如何？",
                    "result_shape",
                ),
                _item("result.compare", "比较前几名", "比较排名前五的差异", "result_shape"),
                _item("result.explain", "解释排名", "为什么会形成这个排名？", "evidence"),
            ]
        else:
            suggestions = [
                _item("metric.trend", "查看月度趋势", f"按月份展开{metric}", "metric_context"),
                _item("metric.compare", "对比上月", f"{metric}与上月相比如何？", "metric_context"),
                _item("result.explain", "解释结果", "为什么会这样？", "evidence"),
            ]
    elif "catalog_result" in artifact_types:
        suggestions = [
            _item("catalog.fields", "查看字段", "这些表分别有哪些字段？", "catalog"),
            _item("catalog.quality", "定位质量数据", "哪些表包含质量检验数据？", "catalog"),
            _item(
                "catalog.metrics", "查看可分析指标", "基于这些数据可以分析哪些质量指标？", "catalog"
            ),
        ]
    else:
        suggestions = [
            _item("start.catalog", "查看数据目录", "数据库里有哪些表？", "capability"),
            _item("start.metric", "分析质量指标", "本月不良率是多少？", "capability"),
            _item("start.help", "查看能力", "你能帮我做什么？", "capability"),
        ]
    return suggestions[:3]


def _item(
    identifier: str,
    label: str,
    message: str,
    source: str,
) -> AnalysisSuggestedFollowUpResponse:
    return AnalysisSuggestedFollowUpResponse(
        id=identifier,
        label=label,
        message=message,
        source=source,
    )
