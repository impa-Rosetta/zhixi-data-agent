import uuid

from sqlalchemy.orm import Session

from packages.platform_core.models import AuditEvent


def add_audit_event(
    db: Session,
    *,
    action: str,
    outcome: str,
    resource_type: str,
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            action=action,
            outcome=outcome,
            resource_type=resource_type,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            resource_id=resource_id,
            detail=detail,
        )
    )
