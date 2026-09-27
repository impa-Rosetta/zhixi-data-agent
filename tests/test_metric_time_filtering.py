from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from apps.worker import analysis_runtime
from packages.agent_core.contracts import AnalysisPlan, AnalysisStep


def test_metric_execution_converts_relative_range_to_parameterized_filters(monkeypatch) -> None:
    captured = {}

    def fake_compile(db, *, workspace_id, actor_user_id, payload):
        captured["payload"] = payload
        return SimpleNamespace(id=uuid4())

    def fake_execute(db, *, workspace_id, actor_user_id, validated_query_id):
        return SimpleNamespace(
            id=uuid4(),
            status="succeeded",
            columns=["inspection_time", "defect_rate"],
            rows=[["2026-07-01", 1.75], ["2026-08-01", 2.75]],
            row_count=2,
            truncated=False,
            evidence_digest="a" * 64,
            trust="trusted",
        )

    monkeypatch.setattr(analysis_runtime, "compile_query", fake_compile)
    monkeypatch.setattr(analysis_runtime, "execute_query", fake_execute)
    run = SimpleNamespace(
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        workspace_id=uuid4(),
        created_by_user_id=uuid4(),
    )
    plan = AnalysisPlan(
        goal="最近三个月不良率趋势",
        steps=(
            AnalysisStep(
                id="trusted_metric_query",
                tool="query.metric",
                arguments={
                    "semantic_model_id": str(uuid4()),
                    "metrics": ["defect_rate"],
                    "dimensions": ["inspection_time"],
                    "time_dimension": "inspection_time",
                    "time_range": "最近三个月",
                    "time_grain": "month",
                    "limit": 200,
                },
                expected_evidence=("validated_query",),
            ),
        ),
    )

    analysis_runtime._execute_metric(None, run, plan)

    payload = captured["payload"]
    assert [(item.dimension, item.operator) for item in payload.filters] == [
        ("inspection_time", "gte"),
        ("inspection_time", "lt"),
    ]
    assert payload.filters[0].value == datetime(2026, 7, 1, tzinfo=UTC)
    assert payload.filters[1].value == datetime(2026, 10, 1, tzinfo=UTC)
