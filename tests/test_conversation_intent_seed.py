from types import SimpleNamespace
from uuid import uuid4

from packages.agent_core.contracts import Intent
from packages.agent_core.conversation_runtime import _previous_intent_run


class _IntentRows:
    def __init__(self, *runs: SimpleNamespace) -> None:
        self._runs = runs

    def scalars(self, _statement: object) -> tuple[SimpleNamespace, ...]:
        return self._runs


def test_capability_help_is_skipped_when_selecting_follow_up_business_context() -> None:
    capability_run = SimpleNamespace(
        context={
            "intent": Intent(
                task_type="capability_help",
                goal="你能帮我做什么？",
                confidence=1.0,
            ).model_dump(mode="json")
        }
    )
    business_run = SimpleNamespace(
        context={
            "intent": Intent(
                task_type="trend",
                goal="最近三个月不良率趋势",
                metrics=("不良率",),
                time_range="最近三个月",
                output=("time_series",),
                confidence=1.0,
            ).model_dump(mode="json")
        }
    )
    conversation_id = uuid4()

    previous_run, intent = _previous_intent_run(
        _IntentRows(capability_run, business_run),  # type: ignore[arg-type]
        run=SimpleNamespace(workspace_id=uuid4(), conversation_id=conversation_id),
        turn=SimpleNamespace(sequence=3),
    )

    assert previous_run is business_run
    assert intent is not None and intent.task_type == "trend"


def test_only_non_business_history_starts_a_fresh_topic() -> None:
    capability_run = SimpleNamespace(
        context={
            "intent": Intent(
                task_type="capability_help",
                goal="你能帮我做什么？",
                confidence=1.0,
            ).model_dump(mode="json")
        }
    )

    previous_run, intent = _previous_intent_run(
        _IntentRows(capability_run),  # type: ignore[arg-type]
        run=SimpleNamespace(workspace_id=uuid4(), conversation_id=uuid4()),
        turn=SimpleNamespace(sequence=2),
    )

    assert previous_run is None
    assert intent is None
