"""Conservative adapter from persisted Agent runs to deterministic evaluation inputs."""

from __future__ import annotations

from pydantic import ValidationError

from packages.agent_core.contracts import ClarificationRequest
from packages.evaluation.answer_claims import verify_answer_claims
from packages.evaluation.contracts import ObservedOutcome
from packages.shared_contracts.agents import AnalysisRunViewResponse


def observe_clarification_run(view: AnalysisRunViewResponse) -> ObservedOutcome:
    """Only score clarification when its question was actually shown to the user."""
    if view.run.status != "waiting_for_clarification":
        raise ValueError("only waiting clarification runs can be observed by this adapter")
    tool_calls = tuple(item.tool_name for item in view.tool_calls)
    raw_request = view.run.context.get("clarification")
    try:
        request = ClarificationRequest.model_validate(raw_request)
    except ValidationError:
        request = None
    last_message = view.messages[-1] if view.messages else None
    interaction = (
        last_message.context_patch.get("interaction") if last_message is not None else None
    )
    question_shown = (
        request is not None
        and last_message is not None
        and last_message.role == "assistant"
        and last_message.content == request.question
        and isinstance(interaction, dict)
        and interaction.get("kind") == "clarification"
    )
    safe_pause = (
        not tool_calls and not view.artifacts and not view.evidence and not view.validations
    )
    return ObservedOutcome(
        status="clarification" if question_shown and safe_pause else "failed",
        tool_calls=tool_calls,
        evidence_count=len(view.evidence),
    )


def observe_completed_run(view: AnalysisRunViewResponse) -> ObservedOutcome:
    """Observe a completed run; other states require their own explicit adapters."""
    if view.run.status != "completed":
        raise ValueError("only completed runs can be observed by this adapter")
    context = view.run.context
    raw_intent = context.get("intent")
    raw_binding = context.get("binding")
    task_type = raw_intent.get("task_type") if isinstance(raw_intent, dict) else None
    metric_keys = raw_binding.get("metric_keys") if isinstance(raw_binding, dict) else None
    if task_type is not None and not isinstance(task_type, str):
        raise ValueError("stored task type is malformed")
    if metric_keys is None:
        metrics: tuple[str, ...] = ()
    elif isinstance(metric_keys, list) and all(isinstance(key, str) for key in metric_keys):
        metrics = tuple(metric_keys)
    else:
        raise ValueError("stored metric binding is malformed")

    claims = verify_answer_claims(view)
    validations_passed = any(
        item.validation_type == "evidence" and item.outcome == "passed" for item in view.validations
    )
    return ObservedOutcome(
        status="completed",
        task_type=task_type,
        metric_ids=metrics,
        tool_calls=tuple(item.tool_name for item in view.tool_calls),
        numbers=claims.displayed_numbers,
        evidence_numbers=claims.evidence_numbers,
        evidence_count=len(view.evidence),
        validation_passed=validations_passed,
        answer_claims_valid=claims.status == "verified" if claims.status != "unverified" else None,
    )
