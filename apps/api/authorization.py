import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from apps.api.dependencies import require_membership
from packages.platform_core.models import Membership, User
from packages.platform_core.policy import Action, PolicyRequest, is_allowed


def authorize(
    db: Session,
    *,
    user: User,
    workspace_id: uuid.UUID,
    action: Action,
) -> Membership:
    membership = require_membership(db, user, workspace_id)
    request = PolicyRequest(
        actor_user_id=user.id,
        actor_workspace_id=workspace_id,
        resource_workspace_id=workspace_id,
        role=membership.role,
        action=action,
    )
    if not is_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Action is not permitted")
    return membership
