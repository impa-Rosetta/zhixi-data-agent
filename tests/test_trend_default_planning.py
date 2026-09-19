from packages.agent_core.contracts import Intent
from packages.agent_core.planner import PublishedSemantic, bind_intent, create_plan, route_intent
from packages.semantic_model.manufacturing import manufacturing_quality_template


def test_trend_defaults_to_unique_temporal_dimension_and_month_grain() -> None:
    intent = Intent(
        task_type="trend",
        goal="最近三个月不良率趋势",
        metrics=("不良率",),
        time_range="最近三个月",
        output=("趋势",),
        confidence=1.0,
    )
    semantic = PublishedSemantic(
        model_id="model-1",
        version_id="version-1",
        document=manufacturing_quality_template(),
    )

    route = route_intent(intent)
    binding = bind_intent(intent, (semantic,))
    plan = create_plan(intent, binding)
    query = plan.steps[0].arguments

    assert route.defaults_applied["dimensions"] == "time"
    assert binding.dimension_keys == ("inspection_time",)
    assert binding.time_dimension_key == "inspection_time"
    assert query["dimensions"] == ["inspection_time"]
    assert query["time_grain"] == "month"
