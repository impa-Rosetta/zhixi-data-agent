import uuid
from decimal import Decimal

from packages.agent_core.contracts import ClarificationRequest, Intent
from packages.agent_core.presentation import (
    clarification_presentation,
    failure_presentation,
    query_presentation,
)


def test_clarification_is_a_direct_agent_question_with_quick_replies() -> None:
    response = clarification_presentation(
        ClarificationRequest(
            reason_code="metric_required",
            question="你希望分析哪个指标？",
            missing_fields=("metrics",),
            suggested_answers=("分析不良率", "分析一次通过率"),
            resume_node="understand",
        )
    )

    assert response.content == "你希望分析哪个指标？"
    assert response.context_patch["interaction"] == {
        "kind": "clarification",
        "quick_replies": ["分析不良率", "分析一次通过率"],
        "retryable": False,
    }
    assert "agent.clarification_required" not in response.content


def test_permission_failure_never_echoes_internal_resource_or_code() -> None:
    response = failure_presentation("connector.permission_denied", retryable=False)

    assert "没有执行这项分析所需的数据访问权限" in response.content
    assert "没有读取相关数据" in response.content
    assert "connector.permission_denied" not in response.content
    assert response.context_patch["technical"]["code"] == "connector.permission_denied"


def test_mapping_failure_explains_data_readiness_and_offers_alternatives() -> None:
    response = failure_presentation(
        "query.mapping_incomplete",
        retryable=False,
        metric_names=("一次通过率",),
    )

    assert "一次通过率" in response.content
    assert "数据模型" in response.content
    assert "不良率" in response.content
    assert "query.mapping_incomplete" not in response.content


def test_unknown_failure_is_safe_and_actionable() -> None:
    response = failure_presentation("vendor.secret-stack-value", retryable=True)

    assert "vendor.secret-stack-value" not in response.content
    assert "重新尝试" in response.content
    assert response.context_patch["interaction"]["retryable"] is True


def test_single_value_query_result_answers_in_natural_language() -> None:
    response = query_presentation(
        Intent(
            task_type="metric_query",
            goal="不良率是多少",
            metrics=("不良率",),
            confidence=0.99,
        ),
        {
            "columns": ["defect_rate"],
            "rows": [[2.4]],
            "row_count": 1,
            "trust": "trusted",
        },
    )

    assert response.content == "不良率为 2.4。"
    assert response.context_patch["interaction"]["kind"] == "answer"


def test_numeric_answer_claim_references_its_query_evidence() -> None:
    artifact_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    validation_id = uuid.uuid4()
    response = query_presentation(
        Intent(
            task_type="metric_query",
            goal="不良率是多少",
            metrics=("不良率",),
            confidence=0.99,
        ),
        {"columns": ["defect_rate"], "rows": [[Decimal("2.400000000")]]},
        source_artifact_id=artifact_id,
        evidence_id=evidence_id,
        validation_id=validation_id,
    )

    assert response.content == "不良率为 2.4。"
    assert response.context_patch["answer_claims"] == [
        {
            "column": "defect_rate",
            "value": "2.4",
            "artifact_id": str(artifact_id),
            "evidence_id": str(evidence_id),
            "validation_id": str(validation_id),
        }
    ]


def test_decimal_query_result_does_not_expose_database_scale() -> None:
    response = query_presentation(
        Intent(
            task_type="metric_query",
            goal="不良率是多少",
            metrics=("不良率",),
            confidence=0.99,
        ),
        {"columns": ["defect_rate"], "rows": [[Decimal("2.4000000000000000")]]},
    )

    assert response.content == "不良率为 2.4。"


def test_serialized_decimal_query_result_does_not_expose_database_scale() -> None:
    response = query_presentation(
        Intent(
            task_type="metric_query",
            goal="不良率是多少",
            metrics=("不良率",),
            confidence=0.99,
        ),
        {"columns": ["defect_rate"], "rows": [["2.4000000000000000"]]},
    )

    assert response.content == "不良率为 2.4。"


def test_single_point_trend_explains_data_is_insufficient() -> None:
    response = query_presentation(
        Intent(
            task_type="trend",
            goal="最近三个月不良率趋势",
            metrics=("不良率",),
            dimensions=("月份",),
            time_range="最近三个月",
            output=("time_series",),
            confidence=0.99,
        ),
        {
            "columns": ["inspection_time", "defect_rate"],
            "rows": [["2026-09-01", 2.4]],
            "row_count": 1,
        },
    )

    assert "只有 1 个时间点" in response.content
    assert "无法形成有意义的趋势" in response.content


def test_single_point_trend_does_not_claim_hidden_metric_value() -> None:
    response = query_presentation(
        Intent(
            task_type="trend",
            goal="最近三个月不良率趋势",
            metrics=("不良率",),
            output=("time_series",),
            confidence=0.99,
        ),
        {"columns": ["inspection_time", "defect_rate"], "rows": [["2026-09-01", 2.4]]},
        source_artifact_id=uuid.uuid4(),
        evidence_id=uuid.uuid4(),
        validation_id=uuid.uuid4(),
    )

    assert "answer_claims" not in response.context_patch
