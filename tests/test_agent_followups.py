import json

import pytest
from pydantic import ValidationError

from packages.agent_core.contracts import FollowUpDecision, Intent
from packages.agent_core.followups import classify_follow_up
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage


def _intent() -> Intent:
    return Intent(
        task_type="metric_query",
        goal="分析本月不良率",
        metrics=("不良率",),
        confidence=1.0,
    )


@pytest.mark.parametrize(
    ("message", "relation"),
    [
        ("按月份展开", "refine"),
        ("与上月相比", "compare"),
        ("为什么会这样？", "explain"),
        ("继续分析", "continue"),
        ("换个话题，数据库有哪些表", "switch_topic"),
    ],
)
def test_explicit_follow_ups_are_classified_without_model(
    message: str,
    relation: str,
) -> None:
    gateway = FakeGateway([])

    decision, usage = classify_follow_up(gateway, _intent(), message)

    assert decision.relation == relation
    assert usage.model_calls == 0
    assert gateway.calls == []


def test_explicit_time_follow_ups_include_governed_context_patches() -> None:
    gateway = FakeGateway([])

    refine, _ = classify_follow_up(gateway, _intent(), "按月份展开")
    compare, _ = classify_follow_up(gateway, _intent(), "与上月相比")

    assert refine.patch is not None
    assert refine.patch.dimensions == ("月份",)
    assert refine.patch.output == ("time_series",)
    assert compare.patch is not None
    assert compare.patch.dimensions == ("月份",)
    assert compare.patch.comparison == "previous_period"


def test_ambiguous_follow_up_uses_strict_model_fallback() -> None:
    gateway = FakeGateway(
        [
            GatewayResponse(
                "follow-up-1",
                "fake",
                json.dumps(
                    {
                        "relation": "refine",
                        "patch": {"dimensions": ["产线"]},
                        "needs_clarification": False,
                        "clarification_question": None,
                        "confidence": 0.82,
                    },
                    ensure_ascii=False,
                ),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )

    decision, usage = classify_follow_up(gateway, _intent(), "分产线看看")

    assert decision.relation == "refine"
    assert decision.patch is not None
    assert decision.patch.dimensions == ("产线",)
    assert usage.model_calls == 1
    assert len(gateway.calls) == 1


def test_follow_up_contract_rejects_executable_or_inconsistent_payloads() -> None:
    with pytest.raises(ValidationError):
        FollowUpDecision.model_validate(
            {
                "relation": "refine",
                "patch": {"sql": "select * from secrets"},
                "needs_clarification": False,
                "confidence": 1,
            }
        )
    with pytest.raises(ValidationError):
        FollowUpDecision(
            relation="continue",
            needs_clarification=True,
            confidence=0.4,
        )
