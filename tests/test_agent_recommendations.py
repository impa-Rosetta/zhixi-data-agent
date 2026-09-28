import uuid

from packages.agent_core.persistence import AnalysisArtifact, AnalysisRunStatus
from packages.agent_core.recommendations import recommend_follow_ups
from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisMetricContext,
    AnalysisResultContext,
)


def test_recommendations_are_empty_while_a_turn_is_running() -> None:
    assert (
        recommend_follow_ups(
            context=AnalysisConversationContext(),
            run_status=AnalysisRunStatus.RUNNING,
            artifacts=[],
        )
        == []
    )


def test_scalar_metric_recommendations_are_bounded_and_executable_messages() -> None:
    suggestions = recommend_follow_ups(
        context=AnalysisConversationContext(
            metric=AnalysisMetricContext(key="defect_rate", name="不良率"),
            last_result=AnalysisResultContext(
                artifact_id=uuid.uuid4(),
                shape="scalar",
                row_count=1,
                primary_value="2.4",
                unit="%",
            ),
        ),
        run_status=AnalysisRunStatus.COMPLETED,
        artifacts=[],
    )

    assert [item.id for item in suggestions] == [
        "metric.trend",
        "metric.compare",
        "result.explain",
    ]
    assert suggestions[0].message == "按月份展开不良率"
    assert len(suggestions) == 3


def test_catalog_recommendations_never_claim_sample_access() -> None:
    artifact = AnalysisArtifact(
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        artifact_type="catalog_result",
        summary={"samples_included": False},
        content_digest="a" * 64,
    )
    suggestions = recommend_follow_ups(
        context=AnalysisConversationContext(),
        run_status=AnalysisRunStatus.COMPLETED,
        artifacts=[artifact],
    )

    assert [item.id for item in suggestions] == [
        "catalog.fields",
        "catalog.quality",
        "catalog.metrics",
    ]
    assert all("样例" not in item.message for item in suggestions)
