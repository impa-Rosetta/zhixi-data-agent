import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from packages.agent_core.persistence import (
    AnalysisEvent,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
)
from packages.platform_core.models import OutboxEvent
from packages.shared_contracts.agents import (
    AnalysisEventResponse,
    AnalysisRunResponse,
    AppendAnalysisMessageRequest,
    CreateAnalysisRunRequest,
)

TERMINAL = {
    AnalysisRunStatus.COMPLETED,
    AnalysisRunStatus.FAILED,
    AnalysisRunStatus.CANCELLED,
}


class AnalysisRunServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _get_run(db: Session, workspace_id: uuid.UUID, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id, AnalysisRun.workspace_id == workspace_id
        )
    )
    if run is None:
        raise AnalysisRunServiceError("analysis_run.not_found", "Analysis run not found")
    return run


def _response(run: AnalysisRun) -> AnalysisRunResponse:
    return AnalysisRunResponse(
        id=run.id,
        workspace_id=run.workspace_id,
        status=run.status.value,
        current_node=run.current_node,
        context=dict(run.context),
        frozen_versions=dict(run.frozen_versions),
        budget=dict(run.budget),
        model_calls=run.model_calls,
        tool_calls=run.tool_calls,
        total_tokens=run.total_tokens,
        replan_count=run.replan_count,
        error_code=run.error_code,
        version=run.version,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def add_event(
    db: Session,
    run: AnalysisRun,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> AnalysisEvent:
    event = AnalysisEvent(
        workspace_id=run.workspace_id,
        run_id=run.id,
        sequence=run.next_event_sequence,
        event_type=event_type,
        payload=payload or {},
    )
    run.next_event_sequence += 1
    db.add(event)
    return event


def create_run(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: CreateAnalysisRunRequest,
) -> AnalysisRunResponse:
    existing = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.workspace_id == workspace_id,
            AnalysisRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _response(existing)
    budget = {
        "max_model_calls": payload.max_model_calls,
        "max_tool_calls": payload.max_tool_calls,
        "max_total_tokens": payload.max_total_tokens,
        "max_runtime_seconds": payload.max_runtime_seconds,
        "max_replans": 1,
    }
    run = AnalysisRun(
        workspace_id=workspace_id,
        created_by_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        status=AnalysisRunStatus.QUEUED,
        current_node="understand",
        context={"goal": payload.message},
        frozen_versions={},
        budget=budget,
    )
    db.add(run)
    db.flush()
    db.add(
        AnalysisMessage(
            workspace_id=workspace_id,
            run_id=run.id,
            role="user",
            content=payload.message,
            idempotency_key=f"{idempotency_key}:initial",
        )
    )
    add_event(db, run, "run.created", {"status": run.status.value})
    db.add(
        OutboxEvent(
            aggregate_type="analysis_run",
            aggregate_id=run.id,
            event_type="analysis.run.requested",
            payload={"run_id": str(run.id)},
        )
    )
    add_audit_event(
        db,
        action="analysis_run.created",
        outcome="success",
        resource_type="analysis_run",
        resource_id=str(run.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    db.flush()
    return _response(run)


def get_run(db: Session, *, workspace_id: uuid.UUID, run_id: uuid.UUID) -> AnalysisRunResponse:
    return _response(_get_run(db, workspace_id, run_id))


def list_events(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    after: int = 0,
    limit: int = 200,
) -> list[AnalysisEventResponse]:
    _get_run(db, workspace_id, run_id)
    events = db.scalars(
        select(AnalysisEvent)
        .where(
            AnalysisEvent.run_id == run_id,
            AnalysisEvent.workspace_id == workspace_id,
            AnalysisEvent.sequence > after,
        )
        .order_by(AnalysisEvent.sequence)
        .limit(max(1, min(limit, 500)))
    ).all()
    return [
        AnalysisEventResponse(
            sequence=item.sequence,
            event_type=item.event_type,
            payload=dict(item.payload),
            created_at=item.created_at,
        )
        for item in events
    ]


def cancel_run(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> AnalysisRunResponse:
    run = _get_run(db, workspace_id, run_id)
    if run.status in TERMINAL:
        return _response(run)
    now = datetime.now(UTC)
    run.cancel_requested_at = now
    run.finished_at = now
    run.status = AnalysisRunStatus.CANCELLED
    run.current_node = "cancelled"
    run.version += 1
    add_event(db, run, "run.cancelled", {"status": run.status.value})
    add_audit_event(
        db,
        action="analysis_run.cancelled",
        outcome="success",
        resource_type="analysis_run",
        resource_id=str(run.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    db.flush()
    return _response(run)


def append_message(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: AppendAnalysisMessageRequest,
) -> AnalysisRunResponse:
    run = _get_run(db, workspace_id, run_id)
    existing = db.scalar(
        select(AnalysisMessage).where(
            AnalysisMessage.run_id == run_id,
            AnalysisMessage.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _response(run)
    if run.status not in {
        AnalysisRunStatus.WAITING_FOR_CLARIFICATION,
        AnalysisRunStatus.WAITING_FOR_CONFIRMATION,
        AnalysisRunStatus.FAILED_RETRYABLE,
    }:
        raise AnalysisRunServiceError(
            "analysis_run.message_not_allowed", "Run is not waiting for user input"
        )
    db.add(
        AnalysisMessage(
            workspace_id=workspace_id,
            run_id=run.id,
            role="user",
            content=payload.message,
            idempotency_key=idempotency_key,
        )
    )
    was_confirmation = run.status is AnalysisRunStatus.WAITING_FOR_CONFIRMATION
    run.context = {**run.context, "latest_user_message": payload.message}
    run.status = AnalysisRunStatus.QUEUED
    run.current_node = "policy_check" if was_confirmation else "understand"
    run.error_code = None
    run.version += 1
    add_event(db, run, "message.accepted", {"status": run.status.value})
    db.add(
        OutboxEvent(
            aggregate_type="analysis_run",
            aggregate_id=run.id,
            event_type="analysis.run.requested",
            payload={"run_id": str(run.id)},
        )
    )
    add_audit_event(
        db,
        action="analysis_run.message_added",
        outcome="success",
        resource_type="analysis_run",
        resource_id=str(run.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    db.flush()
    return _response(run)


def retry_run(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> AnalysisRunResponse:
    run = _get_run(db, workspace_id, run_id)
    if run.status is not AnalysisRunStatus.FAILED_RETRYABLE:
        raise AnalysisRunServiceError(
            "analysis_run.retry_not_allowed", "Only retryable runs can be resumed"
        )
    run.status = AnalysisRunStatus.QUEUED
    run.error_code = None
    run.version += 1
    add_event(db, run, "run.retry_requested", {"node": run.current_node})
    db.add(
        OutboxEvent(
            aggregate_type="analysis_run",
            aggregate_id=run.id,
            event_type="analysis.run.requested",
            payload={"run_id": str(run.id)},
        )
    )
    add_audit_event(
        db,
        action="analysis_run.retry_requested",
        outcome="success",
        resource_type="analysis_run",
        resource_id=str(run.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    db.flush()
    return _response(run)
