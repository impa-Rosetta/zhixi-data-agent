import json

import pytest

from packages.agent_core.planner import (
    PublishedSemantic,
    SemanticBindingError,
    bind_intent,
    create_plan,
    understand,
)
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.semantic_model.manufacturing import manufacturing_quality_template


def _gateway(content: dict[str, object]) -> FakeGateway:
    return FakeGateway(
        [
            GatewayResponse(
                request_id="fake-1",
                model="fake",
                content=json.dumps(content, ensure_ascii=False),
                reasoning_content=None,
                tool_calls=(),
                finish_reason="stop",
                usage=GatewayUsage(20, 10, 30),
            )
        ]
    )


def test_understand_bind_and_plan_cannot_rewrite_metric_formula() -> None:
    gateway = _gateway(
        {
            "domain": "manufacturing_quality",
            "task_type": "comparison",
            "goal": "比较本月与上月不良率",
            "metrics": ["不良率"],
            "dimensions": ["质检日期"],
            "filters": {},
            "time_range": "this_month",
            "comparison": "previous_period",
            "output": ["table"],
            "ambiguities": [],
            "confidence": 0.97,
        }
    )
    intent, usage = understand(gateway, "比较本月与上月不良率")
    semantic = PublishedSemantic(
        model_id="model-1",
        version_id="version-1",
        document=manufacturing_quality_template(),
    )
    binding = bind_intent(intent, (semantic,))
    plan = create_plan(intent, binding)
    assert usage.total_tokens == 30
    assert binding.metric_keys == ("defect_rate",)
    assert binding.dimension_keys == ("inspection_time",)
    assert plan.steps[0].tool == "query.metric"
    assert "formula" not in plan.steps[0].arguments
    assert "sql" not in plan.steps[0].arguments


def test_low_confidence_and_unknown_metric_require_clarification() -> None:
    intent, _ = understand(
        _gateway(
            {
                "domain": "manufacturing_quality",
                "task_type": "metric_query",
                "goal": "看看那个比例",
                "metrics": [],
                "confidence": 0.4,
            }
        ),
        "看看那个比例",
    )
    with pytest.raises(SemanticBindingError, match="agent.clarification_required"):
        bind_intent(intent, ())
