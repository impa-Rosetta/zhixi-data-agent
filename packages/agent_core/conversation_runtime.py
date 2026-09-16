"""Conversation lifecycle synchronization around immutable analysis runs."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.contracts import Binding, FollowUpDecision, Intent
from packages.agent_core.conversation_context import project_completed_run_context
from packages.agent_core.followups import (
    classify_follow_up,
    classify_follow_up_deterministically,
)
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnStatus,
    AnalysisValidation,
)
from packages.model_gateway import GatewayUsage, ModelGateway, ModelGatewayError
from packages.platform_core.models import OutboxEvent
from packages.shared_contracts.agents import AnalysisConversationContext


def _turn_status(run_status: AnalysisRunStatus) -> AnalysisTurnStatus:
    if run_status is AnalysisRunStatus.QUEUED:
        return AnalysisTurnStatus.QUEUED
    if run_status is AnalysisRunStatus.RUNNING:
        return AnalysisTurnStatus.RUNNING
    if run_status in {
        AnalysisRunStatus.WAITING_FOR_CLARIFICATION,
        AnalysisRunStatus.WAITING_FOR_CONFIRMATION,
        AnalysisRunStatus.FAILED_RETRYABLE,
    }:
        return AnalysisTurnStatus.WAITING_FOR_USER
    if run_status is AnalysisRunStatus.COMPLETED:
        return AnalysisTurnStatus.COMPLETED
    if run_status is AnalysisRunStatus.CANCELLED:
        return AnalysisTurnStatus.CANCELLED
    return AnalysisTurnStatus.FAILED


def _project_completed_context(
    db: Session,
    *,
    run: AnalysisRun,
    turn: AnalysisTurn,
) -> AnalysisConversationContext | None:
    if turn.relation.value == "explain":
        return AnalysisConversationContext.model_validate(turn.context_before).model_copy(
            update={"last_relation": "explain"}
        )
    raw_intent = run.context.get("intent")
    if not isinstance(raw_intent, dict):
        return None
    intent = Intent.model_validate(raw_intent)
    raw_binding = run.context.get("binding")
    binding = Binding.model_validate(raw_binding) if isinstance(raw_binding, dict) else None
    artifact = db.scalar(
        select(AnalysisArtifact)
        .where(
            AnalysisArtifact.workspace_id == run.workspace_id,
            AnalysisArtifact.run_id == run.id,
        )
        .order_by(AnalysisArtifact.created_at.desc(), AnalysisArtifact.id.desc())
        .limit(1)
    )
    evidence = None
    if artifact is not None:
        evidence = db.scalar(
            select(AnalysisEvidence)
            .where(
                AnalysisEvidence.workspace_id == run.workspace_id,
                AnalysisEvidence.run_id == run.id,
                AnalysisEvidence.artifact_id == artifact.id,
            )
            .order_by(AnalysisEvidence.created_at.desc(), AnalysisEvidence.id.desc())
            .limit(1)
        )
    validated = db.scalar(
        select(AnalysisValidation.id)
        .where(
            AnalysisValidation.workspace_id == run.workspace_id,
            AnalysisValidation.run_id == run.id,
            AnalysisValidation.outcome == "passed",
        )
        .limit(1)
    )
    raw_result = run.context.get("result")
    result = dict(raw_result) if isinstance(raw_result, dict) else None
    return project_completed_run_context(
        intent=intent,
        binding=binding,
        relation=turn.relation.value,
        artifact_id=artifact.id if artifact is not None else None,
        evidence_id=evidence.id if evidence is not None else None,
        artifact_type=artifact.artifact_type if artifact is not None else "query_result",
        result=result,
        result_is_validated=validated is not None,
    )


def _previous_intent_run(
    db: Session,
    *,
    run: AnalysisRun,
    turn: AnalysisTurn,
) -> tuple[AnalysisRun | None, Intent | None]:
    rows = db.scalars(
        select(AnalysisRun)
        .join(AnalysisTurn, AnalysisTurn.id == AnalysisRun.turn_id)
        .where(
            AnalysisTurn.workspace_id == run.workspace_id,
            AnalysisTurn.conversation_id == run.conversation_id,
            AnalysisTurn.sequence < turn.sequence,
        )
        .order_by(AnalysisTurn.sequence.desc())
        .limit(20)
    )
    for previous_run in rows:
        raw_intent = previous_run.context.get("intent")
        if isinstance(raw_intent, dict):
            return previous_run, Intent.model_validate(raw_intent)
    return None, None


def prepare_conversation_run(
    db: Session,
    *,
    run: AnalysisRun,
    gateway: ModelGateway,
) -> tuple[FollowUpDecision | None, GatewayUsage]:
    """Classify a new turn at execution time against the latest durable context."""
    if run.conversation_id is None or run.turn_id is None:
        return None, GatewayUsage(model_calls=0)
    turn = db.scalar(
        select(AnalysisTurn).where(
            AnalysisTurn.id == run.turn_id,
            AnalysisTurn.workspace_id == run.workspace_id,
            AnalysisTurn.conversation_id == run.conversation_id,
        )
    )
    conversation = db.scalar(
        select(AnalysisConversation).where(
            AnalysisConversation.id == run.conversation_id,
            AnalysisConversation.workspace_id == run.workspace_id,
        )
    )
    if turn is None or conversation is None or turn.sequence == 1:
        return None, GatewayUsage(model_calls=0)
    previous_run, previous_intent = _previous_intent_run(db, run=run, turn=turn)
    message = str(run.context.get("latest_user_message") or run.context.get("goal") or "")
    deterministic = classify_follow_up_deterministically(
        message,
        has_prior_intent=previous_intent is not None,
    )
    if deterministic is None:
        max_model_calls = run.budget.get("max_model_calls", 6)
        max_total_tokens = run.budget.get("max_total_tokens", 32_000)
        if isinstance(max_model_calls, int) and run.model_calls >= max_model_calls:
            raise ModelGatewayError("agent.model_budget_exhausted")
        if isinstance(max_total_tokens, int) and run.total_tokens >= max_total_tokens:
            raise ModelGatewayError("agent.token_budget_exhausted")
    decision, usage = classify_follow_up(gateway, previous_intent, message)
    turn.relation = type(turn.relation)(decision.relation)
    current_context = AnalysisConversationContext.model_validate(conversation.context)
    turn.context_before = current_context.model_dump(mode="json")
    if decision.relation == "switch_topic":
        context_after = AnalysisConversationContext(
            topic_summary=message[:500],
            last_relation="switch_topic",
        )
    else:
        context_after = current_context.model_copy(
            update={"last_relation": decision.relation}
        )
    turn.context_after = context_after.model_dump(mode="json")
    context = {
        **run.context,
        "latest_user_message": message,
        "conversation_context": current_context.model_dump(mode="json"),
        "follow_up_decision": decision.model_dump(mode="json"),
        "follow_up_relation": decision.relation,
    }
    if previous_run is not None:
        context["previous_run_id"] = str(previous_run.id)
    if decision.relation == "switch_topic":
        context.pop("intent", None)
        context.pop("intent_revision_pending", None)
    elif previous_intent is not None:
        context["intent"] = previous_intent.model_dump(mode="json")
        context["intent_revision_pending"] = decision.relation != "explain"
    run.context = context
    db.flush()
    return decision, usage


def synchronize_conversation_after_run(db: Session, *, run_id: uuid.UUID) -> bool:
    """Project a run state and activate at most one queued successor."""
    run = db.get(AnalysisRun, run_id)
    if run is None or run.conversation_id is None or run.turn_id is None:
        return False
    conversation = db.scalar(
        select(AnalysisConversation)
        .where(
            AnalysisConversation.id == run.conversation_id,
            AnalysisConversation.workspace_id == run.workspace_id,
        )
        .with_for_update()
    )
    turn = db.scalar(
        select(AnalysisTurn).where(
            AnalysisTurn.id == run.turn_id,
            AnalysisTurn.workspace_id == run.workspace_id,
            AnalysisTurn.conversation_id == run.conversation_id,
        )
    )
    if conversation is None or turn is None:
        return False

    desired_status = _turn_status(run.status)
    changed = turn.status is not desired_status
    turn.status = desired_status
    turn.started_at = run.started_at or turn.started_at
    turn.finished_at = run.finished_at or turn.finished_at
    if desired_status is AnalysisTurnStatus.COMPLETED:
        projected = _project_completed_context(db, run=run, turn=turn)
        if projected is not None:
            payload = projected.model_dump(mode="json")
            if turn.context_after != payload:
                turn.context_after = payload
                changed = True
            if conversation.context != payload:
                conversation.context = payload
                changed = True
    if desired_status in {
        AnalysisTurnStatus.QUEUED,
        AnalysisTurnStatus.RUNNING,
        AnalysisTurnStatus.WAITING_FOR_USER,
    }:
        if conversation.active_turn_id != turn.id:
            conversation.active_turn_id = turn.id
            changed = True
    elif conversation.active_turn_id == turn.id:
        next_row = db.execute(
            select(AnalysisTurn, AnalysisRun)
            .join(AnalysisRun, AnalysisRun.id == AnalysisTurn.analysis_run_id)
            .where(
                AnalysisTurn.workspace_id == run.workspace_id,
                AnalysisTurn.conversation_id == conversation.id,
                AnalysisTurn.sequence > turn.sequence,
                AnalysisTurn.status == AnalysisTurnStatus.QUEUED,
                AnalysisRun.status == AnalysisRunStatus.QUEUED,
            )
            .order_by(AnalysisTurn.sequence)
            .limit(1)
        ).one_or_none()
        conversation.active_turn_id = next_row[0].id if next_row is not None else None
        changed = True
        if next_row is not None:
            next_turn, next_run = next_row
            current_context = AnalysisConversationContext.model_validate(
                conversation.context
            ).model_dump(mode="json")
            next_turn.context_before = current_context
            next_turn.context_after = current_context
            next_run.context = {
                **next_run.context,
                "conversation_context": current_context,
            }
            existing_outbox = db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.aggregate_id == next_run.id,
                    OutboxEvent.event_type == "analysis.run.requested",
                )
            )
            if existing_outbox is None:
                db.add(
                    OutboxEvent(
                        aggregate_type="analysis_run",
                        aggregate_id=next_run.id,
                        event_type="analysis.run.requested",
                        payload={"run_id": str(next_run.id)},
                    )
                )
    if changed:
        conversation.version += 1
        conversation.updated_at = datetime.now(UTC)
    db.flush()
    return changed
