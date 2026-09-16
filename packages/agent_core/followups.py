"""Safe follow-up classification with deterministic rules before model fallback."""

from __future__ import annotations

from packages.agent_core.contracts import ContextPatch, FollowUpDecision, Intent
from packages.model_gateway import GatewayMessage, GatewayRequest, GatewayUsage, ModelGateway

_EXPLAIN_MARKERS = ("为什么", "解释一下", "怎么理解", "原因", "说明一下")
_COMPARE_MARKERS = (
    "相比",
    "比较",
    "对比",
    "环比",
    "同比",
    "上月",
    "上周",
    "去年",
    "上一期",
)
_REFINE_MARKERS = (
    "按月",
    "每月",
    "月度",
    "按周",
    "每周",
    "按天",
    "每日",
    "按季度",
    "按年",
    "换成",
    "改成",
    "只看",
    "筛选",
    "展开",
)
_CONTINUE_MARKERS = ("继续", "接着", "然后", "再看", "再分析", "还有呢")
_SWITCH_MARKERS = ("换个话题", "新问题", "另外问", "不谈这个", "先不看这个")
_CAPABILITY_OR_CATALOG_MARKERS = (
    "你是谁",
    "你能做什么",
    "有什么功能",
    "有哪些数据源",
    "有哪些表",
    "有什么数据",
)


def _normalized(message: str) -> str:
    return "".join(message.casefold().split())


def classify_follow_up_deterministically(
    message: str,
    *,
    has_prior_intent: bool = True,
) -> FollowUpDecision | None:
    """Classify explicit high-frequency expressions without spending a model call."""
    normalized = _normalized(message)
    if not has_prior_intent:
        return FollowUpDecision(relation="switch_topic", confidence=1.0)
    if any(marker in normalized for marker in _CAPABILITY_OR_CATALOG_MARKERS):
        return FollowUpDecision(relation="switch_topic", confidence=1.0)
    if any(marker in normalized for marker in _SWITCH_MARKERS):
        return FollowUpDecision(relation="switch_topic", confidence=1.0)
    if any(marker in normalized for marker in _EXPLAIN_MARKERS):
        return FollowUpDecision(relation="explain", confidence=1.0)
    if any(marker in normalized for marker in _COMPARE_MARKERS):
        comparison = (
            "previous_year"
            if "同比" in normalized or "去年" in normalized
            else "previous_period"
        )
        return FollowUpDecision(
            relation="compare",
            patch=ContextPatch(comparison=comparison),
            confidence=1.0,
        )
    if any(marker in normalized for marker in _REFINE_MARKERS):
        output = ("time_series",) if any(
            marker in normalized
            for marker in ("按月", "每月", "月度", "按周", "每周", "按天", "每日", "按季度", "按年")
        ) else None
        return FollowUpDecision(
            relation="refine",
            patch=ContextPatch(output=output) if output is not None else None,
            confidence=1.0,
        )
    if any(marker in normalized for marker in _CONTINUE_MARKERS):
        return FollowUpDecision(relation="continue", confidence=1.0)
    return None


def classify_follow_up(
    gateway: ModelGateway,
    previous: Intent | None,
    message: str,
) -> tuple[FollowUpDecision, GatewayUsage]:
    """Return a strict relation candidate; local code remains responsible for execution."""
    deterministic = classify_follow_up_deterministically(
        message,
        has_prior_intent=previous is not None,
    )
    if deterministic is not None:
        return deterministic, GatewayUsage(model_calls=0)
    prompt = (
        "Classify the new manufacturing analytics message relative to the prior intent. "
        "Choose exactly one relation: continue, refine, explain, compare, or switch_topic. "
        "Use a ContextPatch only for safe metric, dimension, filter, time, comparison, or "
        "output changes. If the relationship is genuinely ambiguous, ask one concise natural "
        "language clarification question. Never emit SQL, formulas, code, tool names, "
        "credentials, permissions, or hidden reasoning. "
        f"Prior intent: {previous.model_dump(mode='json') if previous is not None else None}. "
        f"New message: {message}"
    )
    result = gateway.generate_structured(
        GatewayRequest(
            messages=(GatewayMessage(role="user", content=prompt),),
            thinking=False,
            max_tokens=700,
        ),
        FollowUpDecision,
    )
    return FollowUpDecision.model_validate(result.output), result.usage
