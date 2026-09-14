import json

import pytest

from packages.agent_core.contracts import Intent
from packages.agent_core.planner import (
    PublishedSemantic,
    SemanticBindingError,
    bind_intent,
    create_plan,
    revise_intent,
    route_intent,
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


@pytest.mark.parametrize(
    "question",
    ["这是个什么 Agent", "你能做什么", "介绍一下你的功能", "What can you do?"],
)
def test_unambiguous_capability_questions_bypass_model_classification(question: str) -> None:
    intent, usage = understand(
        _gateway(
            {
                "domain": "manufacturing_quality",
                "task_type": "unsupported",
                "goal": "错误的模型分类",
                "metrics": [],
                "confidence": 0.9,
            }
        ),
        question,
    )

    assert intent.task_type == "capability_help"
    assert intent.goal == question
    assert usage.model_calls == 0
    assert usage.total_tokens == 0


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
    with pytest.raises(SemanticBindingError, match="agent.clarification_required") as error:
        bind_intent(intent, ())
    assert error.value.clarification.reason_code == "metric_required"
    assert error.value.clarification.missing_fields == ("metrics",)


@pytest.mark.parametrize(
    ("task_type", "route", "requires_binding"),
    [
        ("capability_help", "capability_help", False),
        ("catalog_exploration", "catalog_exploration", False),
        ("unsupported", "unsupported", False),
        ("metric_query", "metric_query", True),
    ],
)
def test_route_policy_selects_only_allowed_processing_path(
    task_type: str,
    route: str,
    requires_binding: bool,
) -> None:
    intent, _ = understand(
        _gateway(
            {
                "domain": "manufacturing_quality",
                "task_type": task_type,
                "goal": "检查路由",
                "metrics": ["不良率"] if requires_binding else [],
                "confidence": 0.9,
            }
        ),
        "检查路由",
    )
    decision = route_intent(intent)
    assert decision.route == route
    assert decision.requires_binding is requires_binding
    assert decision.clarification is None


def test_unique_metric_uses_safe_defaults_even_with_low_confidence_and_optional_ambiguity() -> None:
    intent, _ = understand(
        _gateway(
            {
                "domain": "manufacturing_quality",
                "task_type": "metric_query",
                "goal": "分析不良率",
                "metrics": ["不良率"],
                "ambiguities": ["未指定时间范围、产线或工序"],
                "confidence": 0.7,
            }
        ),
        "分析不良率",
    )
    decision = route_intent(intent)
    assert decision.route == "metric_query"
    assert decision.defaults_applied == {
        "time_range": "all_available",
        "dimensions": "aggregate",
    }
    binding = bind_intent(
        intent,
        (
            PublishedSemantic(
                model_id="model-1",
                version_id="version-1",
                document=manufacturing_quality_template(),
            ),
        ),
    )
    assert binding.metric_keys == ("defect_rate",)
    assert binding.confidence == 0.7


def test_ambiguous_semantic_binding_returns_actionable_candidates() -> None:
    intent, _ = understand(
        _gateway(
            {
                "domain": "manufacturing_quality",
                "task_type": "metric_query",
                "goal": "分析不良率",
                "metrics": ["不良率"],
                "confidence": 0.95,
            }
        ),
        "分析不良率",
    )
    semantic = manufacturing_quality_template()
    with pytest.raises(SemanticBindingError) as error:
        bind_intent(
            intent,
            (
                PublishedSemantic("model-1", "version-1", semantic),
                PublishedSemantic("model-2", "version-2", semantic),
            ),
        )
    clarification = error.value.clarification
    assert clarification.reason_code == "semantic_binding_ambiguous"
    assert clarification.question == "“不良率”对应多个已发布口径，请选择一个。"
    assert [candidate.key for candidate in clarification.candidates] == ["model-1", "model-2"]
    assert clarification.resume_node == "bind"


def test_intent_revision_applies_a_strict_patch_without_losing_the_goal() -> None:
    previous = Intent(
        task_type="metric_query",
        goal="分析质量指标",
        metrics=(),
        confidence=0.45,
    )
    gateway = _gateway(
        {
            "mode": "patch",
            "patch": {"metrics": ["不良率"]},
            "replacement": None,
        }
    )
    revised, revision, usage = revise_intent(gateway, previous, "我指的是不良率")
    assert revised.goal == previous.goal
    assert revised.metrics == ("不良率",)
    assert revised.confidence == previous.confidence
    assert revision.mode == "patch"
    assert usage.total_tokens == 30


def test_intent_revision_can_explicitly_replace_the_user_goal() -> None:
    previous = Intent(
        task_type="metric_query",
        goal="分析不良率",
        metrics=("不良率",),
        confidence=0.95,
    )
    gateway = _gateway(
        {
            "mode": "replace",
            "patch": None,
            "replacement": {
                "domain": "manufacturing_quality",
                "task_type": "catalog_exploration",
                "goal": "inspection 表有哪些字段",
                "metrics": [],
                "confidence": 0.98,
            },
        }
    )
    revised, revision, _ = revise_intent(gateway, previous, "改成查看 inspection 表字段")
    assert revised.task_type == "catalog_exploration"
    assert revised.goal == "inspection 表有哪些字段"
    assert revision.mode == "replace"
