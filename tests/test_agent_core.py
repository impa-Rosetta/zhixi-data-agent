import pytest

from packages.agent_core.contracts import AnalysisPlan, AnalysisStep, ContextPatch, Intent
from packages.agent_core.graph import build_agent_graph
from packages.toolkit import build_default_registry


def test_plans_are_declarative_and_reject_free_code_or_sql() -> None:
    with pytest.raises(ValueError):
        AnalysisStep(
            id="query",
            tool="query.metric",
            arguments={"sql": "DROP TABLE orders"},
            expected_evidence=("query",),
        )
    with pytest.raises(ValueError):
        AnalysisPlan(
            goal="分析不良率",
            steps=(
                AnalysisStep(
                    id="code",
                    tool="analysis.describe",
                    arguments={"python": "print('unsafe')"},
                    expected_evidence=("summary",),
                ),
            ),
        )


def test_context_patch_preserves_goal_and_updates_filters() -> None:
    original = Intent(
        domain="manufacturing_quality",
        task_type="metric_query",
        goal="分析最近一个月不良率",
        metrics=("defect_rate",),
        confidence=0.96,
    )
    updated = ContextPatch(filters={"production_line": "A线"}).apply(original)
    assert updated.goal == original.goal
    assert updated.metrics == original.metrics
    assert updated.filters == {"production_line": "A线"}


def test_graph_has_bounded_product_nodes() -> None:
    graph = build_agent_graph().get_graph()
    assert {
        "understand",
        "bind",
        "plan",
        "policy_check",
        "execute",
        "verify",
        "present",
    }.issubset(graph.nodes)


def test_registry_exposes_twelve_versioned_governed_tools() -> None:
    registry = build_default_registry()
    assert len(registry.list_specs()) == 12
    metric = registry.get("query.metric")
    assert metric.version == "1.0.0"
    assert metric.required_action == "analysis.run"
    assert metric.idempotent is True

