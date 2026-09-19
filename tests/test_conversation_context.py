import uuid
from datetime import UTC, datetime

from packages.agent_core.contracts import Binding, Intent
from packages.agent_core.conversation_context import project_completed_run_context


def test_completed_run_projects_only_bounded_verified_context() -> None:
    artifact_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    context = project_completed_run_context(
        intent=Intent(
            task_type="trend",
            goal="按月分析本月不良率",
            metrics=("不良率",),
            dimensions=("月份",),
            filters={"production_line": "A线"},
            time_range="本月",
            comparison="previous_period",
            output=("time_series",),
            confidence=1,
        ),
        binding=Binding(
            semantic_model_id=str(uuid.uuid4()),
            semantic_version_id=str(uuid.uuid4()),
            snapshot_ids=(str(uuid.uuid4()),),
            metric_keys=("defect_rate",),
            dimension_keys=("month",),
            confidence=1,
        ),
        relation="refine",
        artifact_id=artifact_id,
        evidence_id=evidence_id,
        result={"columns": ["month", "defect_rate"], "rows": [["2026-08", 0.03]], "row_count": 1},
        result_is_validated=True,
        reference_time=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert context.metric is not None
    assert context.metric.key == "defect_rate"
    assert context.dimensions[0].key == "month"
    assert context.time_grain == "month"
    assert context.time_range is not None
    assert context.time_range.start.isoformat() == "2026-08-01"
    assert context.time_range.end.isoformat() == "2026-09-01"
    assert context.filters[0].field_key == "production_line"
    assert context.comparison == "previous_period"
    assert context.last_result is not None
    assert context.last_result.artifact_id == artifact_id
    assert context.last_result.evidence_id == evidence_id
    assert context.last_result.shape == "time_series"
    dumped = context.model_dump(mode="json")
    assert "sql" not in dumped
    assert "credentials" not in dumped


def test_unvalidated_result_is_never_inherited() -> None:
    context = project_completed_run_context(
        intent=Intent(
            task_type="metric_query",
            goal="分析不良率",
            metrics=("不良率",),
            confidence=1,
        ),
        binding=None,
        relation="continue",
        artifact_id=uuid.uuid4(),
        result={"rows": [["secret"]], "row_count": 1},
        result_is_validated=False,
    )

    assert context.last_result is None
