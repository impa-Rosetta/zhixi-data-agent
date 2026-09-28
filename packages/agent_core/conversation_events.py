"""Durable conversation event projection and replay helpers."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from time import monotonic

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationEvent,
    AnalysisTurn,
)
from packages.shared_contracts.agents import AnalysisConversationEventResponse


def append_conversation_event(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    event_type: str,
    payload: dict[str, object] | None = None,
    turn_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    run_event_sequence: int | None = None,
) -> AnalysisConversationEvent | None:
    conversation = db.scalar(
        select(AnalysisConversation)
        .where(
            AnalysisConversation.id == conversation_id,
            AnalysisConversation.workspace_id == workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if conversation is None:
        return None
    event = AnalysisConversationEvent(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id=run_id,
        sequence=conversation.next_event_sequence,
        run_event_sequence=run_event_sequence,
        event_type=event_type,
        payload=payload or {},
    )
    conversation.next_event_sequence += 1
    db.add(event)
    return event


def _response(db: Session, event: AnalysisConversationEvent) -> AnalysisConversationEventResponse:
    turn_sequence = None
    if event.turn_id is not None:
        turn_sequence = db.scalar(
            select(AnalysisTurn.sequence).where(
                AnalysisTurn.id == event.turn_id,
                AnalysisTurn.workspace_id == event.workspace_id,
            )
        )
    return AnalysisConversationEventResponse(
        sequence=event.sequence,
        event_type=event.event_type,
        turn_id=event.turn_id,
        run_id=event.run_id,
        turn_sequence=turn_sequence,
        run_event_sequence=event.run_event_sequence,
        payload=dict(event.payload),
        created_at=event.created_at,
    )


def list_conversation_events(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    after: int = 0,
    limit: int = 200,
) -> list[AnalysisConversationEventResponse]:
    conversation = db.scalar(
        select(AnalysisConversation.id).where(
            AnalysisConversation.id == conversation_id,
            AnalysisConversation.workspace_id == workspace_id,
        )
    )
    if conversation is None:
        return []
    events = db.scalars(
        select(AnalysisConversationEvent)
        .where(
            AnalysisConversationEvent.workspace_id == workspace_id,
            AnalysisConversationEvent.conversation_id == conversation_id,
            AnalysisConversationEvent.sequence > max(0, after),
        )
        .order_by(AnalysisConversationEvent.sequence)
        .limit(max(1, min(limit, 500)))
    ).all()
    return [_response(db, event) for event in events]


def encode_conversation_sse(event: AnalysisConversationEventResponse) -> str:
    event_name = event.event_type.replace("\r", "").replace("\n", "")
    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event_name}\ndata: {payload}\n\n"


async def stream_conversation_events(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    after: int = 0,
    poll_interval_seconds: float = 0.5,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    bind = db.get_bind()
    cursor = max(0, after)
    next_heartbeat = monotonic() + max(1.0, heartbeat_seconds)
    while True:

        def read_batch(after_sequence: int) -> tuple[list[AnalysisConversationEventResponse], bool]:
            with Session(bind=bind) as polling_db:
                events = list_conversation_events(
                    polling_db,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    after=after_sequence,
                )
                exists = (
                    polling_db.scalar(
                        select(AnalysisConversation.id).where(
                            AnalysisConversation.id == conversation_id,
                            AnalysisConversation.workspace_id == workspace_id,
                        )
                    )
                    is not None
                )
                return events, exists

        events, exists = await to_thread.run_sync(read_batch, cursor)
        if not exists:
            return
        for event in events:
            cursor = event.sequence
            yield encode_conversation_sse(event)
        now = monotonic()
        if now >= next_heartbeat:
            yield ": keep-alive\n\n"
            next_heartbeat = now + max(1.0, heartbeat_seconds)
        await asyncio.sleep(max(0.05, poll_interval_seconds))
