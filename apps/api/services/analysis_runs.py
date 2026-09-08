import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import monotonic

from anyio import to_thread
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvent,
    AnalysisEvidence,
    AnalysisMessage,
    AnalysisPlanRecord,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStepRecord,
    AnalysisToolCall,
    AnalysisValidation,
)
from packages.platform_core.models import OutboxEvent
from packages.shared_contracts.agents import (
    AnalysisArtifactResponse,
    AnalysisEventResponse,
    AnalysisEvidenceResponse,
    AnalysisMessageResponse,
    AnalysisPlanResponse,
    AnalysisRunPage,
    AnalysisRunResponse,
    AnalysisRunSummaryResponse,
    AnalysisRunViewResponse,
    AnalysisStepResponse,
    AnalysisToolCallResponse,
    AnalysisValidationResponse,
    AppendAnalysisMessageRequest,
    ConfirmAnalysisRunRequest,
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
        cancel_requested_at=run.cancel_requested_at,
        started_at=run.started_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def _summary(run: AnalysisRun) -> AnalysisRunSummaryResponse:
    goal = run.context.get("goal", "")
    return AnalysisRunSummaryResponse(
        id=run.id,
        status=run.status.value,
        current_node=run.current_node,
        goal=goal if isinstance(goal, str) else "",
        error_code=run.error_code,
        model_calls=run.model_calls,
        tool_calls=run.tool_calls,
        total_tokens=run.total_tokens,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def list_runs(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    limit: int = 30,
    offset: int = 0,
) -> AnalysisRunPage:
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    total = db.scalar(
        select(func.count()).select_from(AnalysisRun).where(
            AnalysisRun.workspace_id == workspace_id
        )
    )
    runs = db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.workspace_id == workspace_id)
        .order_by(AnalysisRun.updated_at.desc(), AnalysisRun.id.desc())
        .offset(bounded_offset)
        .limit(bounded_limit)
    ).all()
    return AnalysisRunPage(
        items=[_summary(run) for run in runs],
        total=int(total or 0),
        limit=bounded_limit,
        offset=bounded_offset,
    )


def get_run_view(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AnalysisRunViewResponse:
    run = _get_run(db, workspace_id, run_id)
    messages = db.scalars(
        select(AnalysisMessage)
        .where(
            AnalysisMessage.run_id == run.id,
            AnalysisMessage.workspace_id == workspace_id,
        )
        .order_by(AnalysisMessage.created_at, AnalysisMessage.id)
    ).all()
    plan = db.scalar(
        select(AnalysisPlanRecord)
        .where(
            AnalysisPlanRecord.run_id == run.id,
            AnalysisPlanRecord.workspace_id == workspace_id,
        )
        .order_by(AnalysisPlanRecord.revision.desc())
        .limit(1)
    )
    steps = (
        db.scalars(
            select(AnalysisStepRecord)
            .where(
                AnalysisStepRecord.plan_id == plan.id,
                AnalysisStepRecord.workspace_id == workspace_id,
            )
            .order_by(AnalysisStepRecord.step_key)
        ).all()
        if plan is not None
        else []
    )
    tool_calls = db.scalars(
        select(AnalysisToolCall)
        .where(
            AnalysisToolCall.run_id == run.id,
            AnalysisToolCall.workspace_id == workspace_id,
        )
        .order_by(AnalysisToolCall.created_at, AnalysisToolCall.id)
    ).all()
    artifacts = db.scalars(
        select(AnalysisArtifact)
        .where(
            AnalysisArtifact.run_id == run.id,
            AnalysisArtifact.workspace_id == workspace_id,
        )
        .order_by(AnalysisArtifact.created_at, AnalysisArtifact.id)
    ).all()
    evidence = db.scalars(
        select(AnalysisEvidence)
        .where(
            AnalysisEvidence.run_id == run.id,
            AnalysisEvidence.workspace_id == workspace_id,
        )
        .order_by(AnalysisEvidence.created_at, AnalysisEvidence.id)
    ).all()
    validations = db.scalars(
        select(AnalysisValidation)
        .where(
            AnalysisValidation.run_id == run.id,
            AnalysisValidation.workspace_id == workspace_id,
        )
        .order_by(AnalysisValidation.created_at, AnalysisValidation.id)
    ).all()
    return AnalysisRunViewResponse(
        run=_response(run),
        messages=[
            AnalysisMessageResponse(
                id=item.id,
                role=item.role,
                content=item.content,
                context_patch=dict(item.context_patch),
                created_at=item.created_at,
            )
            for item in messages
        ],
        plan=(
            AnalysisPlanResponse(
                id=plan.id,
                revision=plan.revision,
                goal=plan.goal,
                document=dict(plan.document),
                requires_confirmation=plan.requires_confirmation,
                confirmed_at=plan.confirmed_at,
                created_at=plan.created_at,
            )
            if plan is not None
            else None
        ),
        steps=[
            AnalysisStepResponse(
                id=item.id,
                plan_id=item.plan_id,
                step_key=item.step_key,
                tool_name=item.tool_name,
                arguments=dict(item.arguments),
                dependencies=list(item.dependencies),
                status=item.status.value,
                error_code=item.error_code,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in steps
        ],
        tool_calls=[
            AnalysisToolCallResponse(
                id=item.id,
                step_id=item.step_id,
                tool_name=item.tool_name,
                tool_version=item.tool_version,
                argument_digest=item.argument_digest,
                status=item.status.value,
                result_summary=dict(item.result_summary),
                error_code=item.error_code,
                created_at=item.created_at,
            )
            for item in tool_calls
        ],
        artifacts=[
            AnalysisArtifactResponse(
                id=item.id,
                artifact_type=item.artifact_type,
                summary=dict(item.summary),
                content_digest=item.content_digest,
                created_at=item.created_at,
            )
            for item in artifacts
        ],
        evidence=[
            AnalysisEvidenceResponse(
                id=item.id,
                artifact_id=item.artifact_id,
                evidence_type=item.evidence_type,
                reference=dict(item.reference),
                evidence_digest=item.evidence_digest,
                created_at=item.created_at,
            )
            for item in evidence
        ],
        validations=[
            AnalysisValidationResponse(
                id=item.id,
                validation_type=item.validation_type,
                outcome=item.outcome,
                findings=list(item.findings),
                created_at=item.created_at,
            )
            for item in validations
        ],
        last_event_sequence=max(0, run.next_event_sequence - 1),
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


def encode_sse_event(event: AnalysisEventResponse) -> str:
    event_name = event.event_type.replace("\r", "").replace("\n", "")
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {event.sequence}\nevent: {event_name}\ndata: {payload}\n\n"


async def stream_events(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    after: int = 0,
    poll_interval_seconds: float = 0.5,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    _get_run(db, workspace_id, run_id)
    bind = db.get_bind()
    cursor = max(0, after)
    next_heartbeat = monotonic() + max(1.0, heartbeat_seconds)
    while True:
        def read_batch(
            after_sequence: int,
        ) -> tuple[list[AnalysisEventResponse], AnalysisRunStatus, int]:
            with Session(bind=bind) as polling_db:
                events = list_events(
                    polling_db,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    after=after_sequence,
                    limit=200,
                )
                stream_state = polling_db.execute(
                    select(AnalysisRun.status, AnalysisRun.next_event_sequence).where(
                        AnalysisRun.id == run_id,
                        AnalysisRun.workspace_id == workspace_id,
                    )
                ).one()
                return events, stream_state[0], stream_state[1]

        events, run_status, next_event_sequence = await to_thread.run_sync(read_batch, cursor)
        for event in events:
            cursor = event.sequence
            yield encode_sse_event(event)

        if run_status in TERMINAL and cursor >= next_event_sequence - 1:
            return

        now = monotonic()
        if now >= next_heartbeat:
            yield ": keep-alive\n\n"
            next_heartbeat = now + max(1.0, heartbeat_seconds)
        await asyncio.sleep(max(0.05, poll_interval_seconds))


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
    context = {**run.context, "latest_user_message": payload.message}
    if not was_confirmation:
        for key in ("intent", "binding", "plan"):
            context.pop(key, None)
    run.context = context
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


def confirm_run(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: ConfirmAnalysisRunRequest,
) -> AnalysisRunResponse:
    run = _get_run(db, workspace_id, run_id)
    if run.status is not AnalysisRunStatus.WAITING_FOR_CONFIRMATION:
        raise AnalysisRunServiceError(
            "analysis_run.confirmation_not_allowed", "Run is not waiting for confirmation"
        )
    if payload.approved:
        run.context = {**run.context, "plan_confirmed": True}
        run.status = AnalysisRunStatus.QUEUED
        run.current_node = "execute"
        add_event(db, run, "run.confirmed")
        db.add(
            OutboxEvent(
                aggregate_type="analysis_run",
                aggregate_id=run.id,
                event_type="analysis.run.requested",
                payload={"run_id": str(run.id)},
            )
        )
    else:
        run.status = AnalysisRunStatus.CANCELLED
        run.current_node = "cancelled"
        run.finished_at = datetime.now(UTC)
        add_event(db, run, "run.confirmation_rejected")
    run.version += 1
    add_audit_event(
        db,
        action="analysis_run.confirmed" if payload.approved else "analysis_run.rejected",
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
