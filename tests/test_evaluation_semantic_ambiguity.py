import pytest

from packages.evaluation import run_offline_suite
from packages.evaluation.draft_adapter import draft_case_factory
from packages.evaluation.registry import registered_suite
from packages.evaluation.semantic_ambiguity_fixture import pinned_semantic_ambiguity


def test_semantic_state_cases_preserve_history_and_run_real_agent_clarification() -> None:
    previous = registered_suite("0.1.15")
    suite = registered_suite("0.1.16")
    assert suite.cases[:92] == previous.cases
    assert len(suite.cases) == 99 and not suite.published
    cases = suite.cases[92:]
    for case in cases:
        spec = pinned_semantic_ambiguity(case)
        assert spec is not None
        changed = case.model_copy(
            update={"expected": case.expected.model_copy(update={"numbers": {"fake": 999}})}
        )
        assert pinned_semantic_ambiguity(changed) == spec
        assert not pinned_semantic_ambiguity(case.model_copy(update={"turns": ("替换输入",)}))
        assert not pinned_semantic_ambiguity(case.model_copy(update={"category": "standard"}))
    result = run_offline_suite(suite.model_copy(update={"cases": cases}), draft_case_factory)
    assert result.summary.passed == 7, result.to_json()
    assert result.summary.failed == result.summary.infra_error == result.summary.blocked == 0
    assert len(result.run_references) == 7


@pytest.mark.parametrize("corruption", ["candidate", "reason", "missing", "foreign_leak"])
def test_semantic_clarification_does_not_pass_wrong_candidates_or_private_disclosure(
    monkeypatch, corruption
) -> None:
    import packages.evaluation.semantic_ambiguity_fixture as fixture

    original = fixture.get_run_view

    def changed_view(*args, **kwargs):
        view = original(*args, **kwargs)
        context = dict(view.run.context)
        request = dict(context["clarification"])
        messages = list(view.messages)
        if corruption == "candidate":
            request["candidates"] = []
        elif corruption == "reason":
            request["reason_code"] = "metric_required"
        elif corruption == "missing":
            request["missing_fields"] = ["dimensions"]
        else:
            messages[-1] = messages[-1].model_copy(
                update={"content": "SYNTHETIC_PRIVATE_SEMANTIC_CANARY"}
            )
        context["clarification"] = request
        return view.model_copy(
            update={"run": view.run.model_copy(update={"context": context}), "messages": messages}
        )

    monkeypatch.setattr(fixture, "get_run_view", changed_view)
    suite = registered_suite("0.1.16")
    case_id = (
        "ambiguity-foreign-definition"
        if corruption == "foreign_leak"
        else "ambiguity-two-defect-definitions"
    )
    case = next(case for case in suite.cases if case.id == case_id)
    result = run_offline_suite(suite.model_copy(update={"cases": (case,)}), draft_case_factory)
    assert result.summary.passed == 0 and result.summary.failed == 1


def test_same_persisted_fixture_can_resolve_a_unique_known_metric() -> None:
    from apps.worker.analysis_runtime import _published_semantics
    from packages.agent_core.contracts import Intent
    from packages.agent_core.persistence import AnalysisRun
    from packages.agent_core.planner import bind_intent

    suite = registered_suite("0.1.16")
    case = next(case for case in suite.cases if case.id == "ambiguity-unknown-quality-metric")
    with draft_case_factory(case) as session:
        executed = session.execute()
        run = session.db.get(AnalysisRun, executed.run_ids[0])
        assert run is not None
        semantics = _published_semantics(session.db, run)
        assert len(semantics) == 1
        binding = bind_intent(
            Intent(
                task_type="metric_query", goal="分析不良率", metrics=("不良率",), confidence=0.98
            ),
            semantics,
        )
        assert binding.metric_keys == ("defect_rate",)
