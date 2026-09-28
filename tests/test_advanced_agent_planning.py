import uuid

import pytest

from packages.agent_core.contracts import Binding, Intent
from packages.agent_core.planner import create_plan, route_intent


def intent(task: str, metrics: tuple[str, ...], dimensions: tuple[str, ...] = ("日期",)) -> Intent:
    return Intent(
        task_type=task, goal="分析这些数据", metrics=metrics, dimensions=dimensions, confidence=1
    )


def binding(metrics: tuple[str, ...]) -> Binding:
    return Binding(
        semantic_model_id=str(uuid.uuid4()),
        semantic_version_id=str(uuid.uuid4()),
        snapshot_ids=(str(uuid.uuid4()),),
        metric_keys=metrics,
        dimension_keys=("inspection_time",),
        time_dimension_key="inspection_time",
        confidence=1,
    )


@pytest.mark.parametrize(
    "task,metrics,tool",
    [
        ("correlation", ("x", "y"), "analysis.correlate"),
        ("anomaly_detection", ("y",), "analysis.detect_anomaly"),
    ],
)
def test_advanced_routes_have_real_query_and_analysis_steps(task, metrics, tool) -> None:
    value = intent(task, metrics)
    assert route_intent(value).route == task
    plan = create_plan(value, binding(metrics))
    assert plan.steps[0].tool == "query.metric"
    assert plan.steps[1].tool == tool
    assert plan.steps[1].id == "advanced_analysis"
    assert plan.steps[2].depends_on == ("advanced_analysis",)
    assert plan.requires_confirmation is False


@pytest.mark.parametrize(
    "task,metrics",
    [
        ("correlation", ("x",)),
        ("correlation", ("x", "y", "z")),
        ("anomaly_detection", ("x", "y")),
    ],
)
def test_missing_analysis_fields_are_natural_language_clarifications(task, metrics) -> None:
    route = route_intent(intent(task, metrics))
    assert route.clarification is not None
    assert route.clarification.question
    assert "metrics" in route.clarification.missing_fields


def test_advanced_analysis_requires_explicit_comparison_grain() -> None:
    route = route_intent(intent("correlation", ("x", "y"), ()))
    assert route.clarification is not None
    assert route.clarification.reason_code == "analysis_grain_required"


def test_spearman_selection_survives_the_plan() -> None:
    value = intent("correlation", ("x", "y")).model_copy(update={"analysis_method": "spearman"})
    assert create_plan(value, binding(("x", "y"))).steps[1].arguments["method"] == "spearman"
