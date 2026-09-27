"""Safe, deterministic natural-language presentation for Agent run states."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from packages.agent_core.contracts import ClarificationRequest, Intent

InteractionKind = Literal["answer", "clarification", "error", "unsupported"]


@dataclass(frozen=True)
class AgentPresentation:
    content: str
    context_patch: dict[str, object]


def _presentation(
    content: str,
    *,
    kind: InteractionKind,
    quick_replies: tuple[str, ...] = (),
    retryable: bool = False,
    technical_code: str | None = None,
) -> AgentPresentation:
    patch: dict[str, object] = {
        "interaction": {
            "kind": kind,
            "quick_replies": list(dict.fromkeys(quick_replies))[:6],
            "retryable": retryable,
        }
    }
    if technical_code:
        patch["technical"] = {"code": technical_code, "visible_in_inspector": True}
    return AgentPresentation(content=content, context_patch=patch)


def clarification_presentation(request: ClarificationRequest) -> AgentPresentation:
    replies = (*request.suggested_answers, *(item.label for item in request.candidates))
    return _presentation(
        request.question,
        kind="clarification",
        quick_replies=replies,
        technical_code="agent.clarification_required",
    )


def failure_presentation(
    code: str,
    *,
    retryable: bool,
    metric_names: tuple[str, ...] = (),
) -> AgentPresentation:
    metric = "、".join(_safe_labels(metric_names)) or "这个指标"
    if code in {"connector.permission_denied", "query.permission_denied", "policy.denied"}:
        content = (
            "当前账号没有执行这项分析所需的数据访问权限，我没有读取相关数据。"
            "你可以改用已授权的数据范围，或联系工作区管理员申请权限。"
        )
    elif code in {"query.mapping_incomplete", "query.metric_mapping_missing"}:
        content = (
            f"我识别到你想分析{metric}，但当前发布的数据模型还缺少完成计算所需的字段映射，"
            "因此暂时无法给出可靠结果。你可以先分析不良率或检验数量趋势，"
            "也可以请管理员补充并发布对应映射。"
        )
    elif code == "catalog.not_available":
        content = (
            "当前工作区还没有可供分析的已发布的数据目录。"
            "请先完成数据源扫描并发布目录，然后我就能回答表、字段和数据范围相关问题。"
        )
    elif code == "agent.route_not_available":
        return _presentation(
            "这个问题超出了我当前的数据分析范围。我可以介绍系统能力、查看已授权的数据目录，"
            "或分析已发布的制造质量指标，例如“不良率是多少”或“最近三个月不良率趋势”。",
            kind="unsupported",
            quick_replies=("你能做什么？", "数据库里有哪些表？", "不良率是多少？"),
            technical_code=code,
        )
    elif code == "agent.tool_budget_exhausted":
        content = "这次分析已达到允许的工具调用次数，因此没有继续访问数据。你可以发起一次新的分析。"
    elif code in {"agent.model_budget_exhausted", "agent.token_budget_exhausted"}:
        content = (
            "这次分析已达到模型使用上限。我已经停止继续处理，你可以缩小问题范围后重新发起分析。"
        )
    elif code == "model.not_configured":
        content = "模型服务暂时不可用，我已经保留当前进度。配置完成后可以重新尝试。"
    elif code in {
        "model.rate_limited",
        "model.timeout",
        "model.network_error",
        "model.provider_unavailable",
        "model.retry_exhausted",
    }:
        content = "模型服务暂时没有响应，我已经保留当前进度。请稍后重新尝试。"
    else:
        content = "这次分析没有完成，但没有产生可用结论。" + (
            "当前进度已保留，你可以重新尝试。" if retryable else "你可以调整问题后重新发起分析。"
        )
    return _presentation(content, kind="error", retryable=retryable, technical_code=code)


def query_presentation(
    intent: Intent,
    result: dict[str, object],
    *,
    source_artifact_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
    validation_id: uuid.UUID | None = None,
) -> AgentPresentation:
    rows = result.get("rows")
    columns = result.get("columns")
    safe_rows = rows if isinstance(rows, list) else []
    safe_columns = columns if isinstance(columns, list) else []
    metric = "、".join(_safe_labels(intent.metrics)) or "查询结果"
    displayed_values: list[tuple[str, object]] = []
    time_series_requested = (
        intent.task_type == "trend"
        or "time_series" in intent.output
        or any(marker in item for item in intent.output for marker in ("趋势", "折线"))
    )
    if time_series_requested and len(safe_rows) == 1:
        content = (
            f"我完成了{metric}的查询，但当前范围只有 1 个时间点，无法形成有意义的趋势。"
            "你可以补充更多月份的数据，扩大时间范围，或改为查看本期不同产线或产品的分布。"
        )
    elif len(safe_rows) == 1 and isinstance(safe_rows[0], list) and len(safe_rows[0]) == 1:
        if safe_rows[0][0] is None:
            content = (
                f"当前结果无法计算{metric}，不能把它当作 0。"
                "可能是筛选范围内没有有效数据，或计算所需的分母为零或缺失；"
                "仅凭当前结果还不能确定具体原因。你可以扩大时间范围，"
                "或查看检验数量等基础指标，进一步确认数据情况。"
            )
        else:
            content = f"{metric}为 {_format_value(safe_rows[0][0])}。"
        if (
            safe_rows[0][0] is not None
            and len(safe_columns) == 1
            and isinstance(safe_columns[0], str)
        ):
            displayed_values.append((safe_columns[0], safe_rows[0][0]))
    elif not safe_rows:
        content = f"我完成了{metric}的查询，但在当前授权范围和筛选条件下没有找到数据。"
    else:
        row_count = result.get("row_count")
        count = row_count if isinstance(row_count, int) and row_count >= 0 else len(safe_rows)
        detail = ""
        if len(safe_rows) == 1 and isinstance(safe_rows[0], list) and safe_columns:
            pairs = [
                f"{_safe_label(column)}为 {_format_value(value)}"
                for column, value in zip(safe_columns[:6], safe_rows[0][:6], strict=False)
            ]
            displayed_values.extend(
                (column, value)
                for column, value in zip(safe_columns[:6], safe_rows[0][:6], strict=False)
                if isinstance(column, str)
            )
            detail = "，" + "，".join(pairs) if pairs else ""
        content = (
            f"我已经完成{metric}的分析，共得到 {count} 行结果{detail}。详细数据和证据见下方结果。"
        )
    presentation = _presentation(content, kind="answer")
    if source_artifact_id is None or evidence_id is None or validation_id is None:
        return presentation
    claims = [
        claim
        for column, value in displayed_values
        if (claim := _numeric_claim(column, value, source_artifact_id, evidence_id, validation_id))
        is not None
    ]
    if not claims:
        return presentation
    return AgentPresentation(
        content=presentation.content,
        context_patch={**presentation.context_patch, "answer_claims": claims},
    )


def _numeric_claim(
    column: str,
    value: object,
    artifact_id: uuid.UUID,
    evidence_id: uuid.UUID,
    validation_id: uuid.UUID,
) -> dict[str, str] | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return None
    displayed = _format_value(value)
    try:
        number = Decimal(displayed)
    except (ValueError, ArithmeticError):
        return None
    if not number.is_finite():
        return None
    return {
        "column": _safe_label(column),
        "value": displayed,
        "artifact_id": str(artifact_id),
        "evidence_id": str(evidence_id),
        "validation_id": str(validation_id),
    }


def catalog_presentation(result: dict[str, object]) -> AgentPresentation:
    sources = result.get("sources")
    safe_sources = sources if isinstance(sources, list) else []
    relation_count = sum(
        len(source["relations"])
        for source in safe_sources
        if isinstance(source, dict) and isinstance(source.get("relations"), list)
    )
    if relation_count:
        content = (
            f"我在你有权访问的已发布数据目录中找到了 {relation_count} 个匹配的数据表，详情如下。"
        )
    else:
        content = (
            "我检查了你有权访问的已发布数据目录，但没有找到匹配的数据表或字段。"
            "你可以换一个名称再问我。"
        )
    return _presentation(content, kind="answer")


def answer_presentation(content: str) -> AgentPresentation:
    return _presentation(content.strip() or "这项操作已经完成。", kind="answer")


def small_talk_presentation(content: str) -> AgentPresentation:
    return _presentation(
        content.strip() or "你好！今天想分析什么？",
        kind="answer",
        quick_replies=("你能做什么？", "数据库里有哪些表？", "不良率是多少？"),
    )


def _safe_labels(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(label for value in values if (label := _safe_label(value)))


def _safe_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.strip()[:80] if character.isprintable())


def _format_value(value: object) -> str:
    if value is None:
        return "空值"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float):
            return f"{value:g}"
        if isinstance(value, Decimal):
            normalized = format(value.normalize(), "f")
            return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized
        return str(value)
    if isinstance(value, str):
        safe = _safe_label(value)
        if "." in safe:
            whole, fractional = safe.split(".", 1)
            if whole.lstrip("-").isdigit() and fractional.isdigit():
                return safe.rstrip("0").rstrip(".")
        return safe or "空字符串"
    return "一个结构化结果"
