"""Conservative adapter from persisted Agent runs to deterministic evaluation inputs."""

from __future__ import annotations

from packages.evaluation.answer_claims import verify_answer_claims
from packages.evaluation.contracts import ObservedOutcome
from packages.shared_contracts.agents import AnalysisRunViewResponse


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
