import uuid
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisConversationPage,
    AnalysisConversationResponse,
    AnalysisConversationSummaryResponse,
    AnalysisConversationViewResponse,
    AnalysisTurnResponse,
    CreateAnalysisConversationRequest,
    SendAnalysisConversationMessageRequest,
)


def test_conversation_context_accepts_only_versioned_business_fields() -> None:
    context = AnalysisConversationContext.model_validate(
        {
            "version": 1,
            "topic_summary": "查看制造质量的不良率",
            "metric": {"key": "defect_rate", "name": "不良率"},
            "dimensions": [{"key": "inspection_month", "name": "检验月份"}],
            "time_range": {"start": "2026-01-01", "end": "2026-08-31"},
            "time_grain": "month",
            "comparison": "previous_period",
            "sort": {"direction": "desc", "limit": 10},
            "semantic_version": {
                "model_id": str(uuid.uuid4()),
                "version": 3,
            },
            "last_result": {
                "artifact_id": str(uuid.uuid4()),
                "evidence_id": str(uuid.uuid4()),
                "shape": "scalar",
                "row_count": 1,
                "primary_value": "2.4%",
                "unit": "%",
            },
            "last_relation": "continue",
        }
    )

    assert context.version == 1
    assert context.time_range is not None
    assert context.time_range.start == date(2026, 1, 1)
    assert context.last_result is not None
    assert context.last_result.primary_value == "2.4%"


@pytest.mark.parametrize(
    "forbidden",
    [
        {"sql": "select * from secret"},
        {"credentials": {"password": "secret"}},
        {"reasoning_content": "private chain of thought"},
        {"exception_stack": "Traceback ..."},
        {"queue_key": "internal"},
    ],
)
def test_conversation_context_rejects_internal_or_sensitive_fields(
    forbidden: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AnalysisConversationContext.model_validate({"version": 1, **forbidden})


def test_conversation_context_rejects_unbounded_collections_and_wrong_version() -> None:
    with pytest.raises(ValidationError):
        AnalysisConversationContext.model_validate(
            {
                "version": 1,
                "dimensions": [
                    {"key": f"dimension_{index}", "name": f"维度 {index}"}
                    for index in range(11)
                ],
            }
        )
    with pytest.raises(ValidationError):
        AnalysisConversationContext.model_validate({"version": 2})
    with pytest.raises(ValidationError):
        AnalysisConversationContext.model_validate(
            {
                "version": 1,
                "filters": [
                    {"field_key": "factory", "operator": "eq", "value": "x" * 501}
                ],
            }
        )
    with pytest.raises(ValidationError):
        AnalysisConversationContext.model_validate({"version": 1, "time_range": {}})


def test_conversation_requests_are_strict_and_bounded() -> None:
    request = CreateAnalysisConversationRequest(message="本月不良率是多少？")
    follow_up = SendAnalysisConversationMessageRequest(message="按月份展开")

    assert request.max_model_calls == 6
    assert follow_up.message == "按月份展开"
    with pytest.raises(ValidationError):
        CreateAnalysisConversationRequest.model_validate(
            {"message": "本月不良率是多少？", "api_key": "must-not-pass"}
        )
    with pytest.raises(ValidationError):
        SendAnalysisConversationMessageRequest(message="x" * 10_001)


def test_public_conversation_view_has_no_internal_idempotency_or_queue_fields() -> None:
    now = datetime.now(UTC)
    conversation_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    run_id = uuid.uuid4()
    conversation = AnalysisConversationResponse(
        id=conversation_id,
        workspace_id=uuid.uuid4(),
        title="本月不良率",
        status="active",
        context=AnalysisConversationContext(),
        active_turn_id=turn_id,
        last_turn_sequence=1,
        version=1,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    turn = AnalysisTurnResponse(
        id=turn_id,
        sequence=1,
        parent_turn_id=None,
        analysis_run_id=run_id,
        relation="initial",
        status="running",
        queued_at=now,
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    view = AnalysisConversationViewResponse(
        conversation=conversation,
        turns=[turn],
        total_turns=1,
        limit=20,
        offset=0,
    )

    payload = view.model_dump(mode="json")
    serialized = str(payload)
    assert "idempotency" not in serialized
    assert "queue_key" not in serialized
    assert "reasoning" not in serialized
    assert "sql" not in serialized.lower()


def test_conversation_page_enforces_pagination_bounds() -> None:
    now = datetime.now(UTC)
    summary = AnalysisConversationSummaryResponse(
        id=uuid.uuid4(),
        title="不良率分析",
        status="active",
        active_turn_id=None,
        active_turn_status=None,
        last_turn_sequence=0,
        last_message_preview=None,
        created_at=now,
        updated_at=now,
    )
    page = AnalysisConversationPage(items=[summary], total=1, limit=20, offset=0)

    assert page.total == 1
    with pytest.raises(ValidationError):
        AnalysisConversationPage(items=[], total=0, limit=101, offset=0)
