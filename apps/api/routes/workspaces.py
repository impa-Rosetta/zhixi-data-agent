import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from apps.api.audit import add_audit_event
from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from packages.platform_core.models import Membership, WorkspaceInvitation, WorkspaceRole
from packages.platform_core.policy import Action
from packages.platform_core.security import hash_refresh_token
from packages.shared_contracts.auth import (
    InvitationResponse,
    MemberCreateRequest,
    MemberResponse,
    MemberRoleRequest,
    WorkspaceSummary,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _ensure_role_can_be_assigned(actor_role: WorkspaceRole, target_role: WorkspaceRole) -> None:
    if target_role is WorkspaceRole.SYSTEM_ADMIN and actor_role is not WorkspaceRole.SYSTEM_ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a system administrator may assign this role"
        )


def _member_response(membership: Membership) -> MemberResponse:
    return MemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(user: CurrentUser) -> list[WorkspaceSummary]:
    return [
        WorkspaceSummary(
            id=item.workspace.id,
            name=item.workspace.name,
            slug=item.workspace.slug,
            role=item.role,
        )
        for item in user.memberships
    ]


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
def list_members(workspace_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[MemberResponse]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.MEMBER_READ)
    members = db.scalars(
        select(Membership)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    ).all()
    return [_member_response(item) for item in members]


@router.post(
    "/{workspace_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    workspace_id: uuid.UUID,
    payload: MemberCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> InvitationResponse:
    actor_membership = authorize(
        db, user=user, workspace_id=workspace_id, action=Action.MEMBER_INVITE
    )
    _ensure_role_can_be_assigned(actor_membership.role, payload.role)
    normalized_email = payload.email.strip().lower()
    existing_invitation = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.email == normalized_email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
    )
    if existing_invitation is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An active invitation already exists")
    raw_token = secrets.token_urlsafe(48)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=normalized_email,
        role=payload.role,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        invited_by_user_id=user.id,
    )
    db.add(invitation)
    db.flush()
    add_audit_event(
        db,
        action="member.invite",
        outcome="success",
        resource_type="workspace_invitation",
        actor_user_id=user.id,
        workspace_id=workspace_id,
        resource_id=str(invitation.id),
        detail=f"role={payload.role.value}",
    )
    db.commit()
    db.refresh(invitation)
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        invite_token=raw_token,
    )


@router.patch("/{workspace_id}/members/{membership_id}", response_model=MemberResponse)
def update_member_role(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberRoleRequest,
    db: DbSession,
    user: CurrentUser,
) -> MemberResponse:
    actor_membership = authorize(
        db, user=user, workspace_id=workspace_id, action=Action.MEMBER_ROLE_UPDATE
    )
    _ensure_role_can_be_assigned(actor_membership.role, payload.role)
    membership = db.get(Membership, membership_id)
    if membership is None or membership.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    if (
        membership.role is WorkspaceRole.SYSTEM_ADMIN
        and actor_membership.role is not WorkspaceRole.SYSTEM_ADMIN
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a system administrator may modify this role"
        )
    if membership.role in {
        WorkspaceRole.SYSTEM_ADMIN,
        WorkspaceRole.WORKSPACE_ADMIN,
    } and payload.role not in {
        WorkspaceRole.SYSTEM_ADMIN,
        WorkspaceRole.WORKSPACE_ADMIN,
    }:
        admin_count = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role.in_([WorkspaceRole.SYSTEM_ADMIN, WorkspaceRole.WORKSPACE_ADMIN]),
            )
        )
        if admin_count == 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Workspace must retain an administrator")
    membership.role = payload.role
    add_audit_event(
        db,
        action="member.role.update",
        outcome="success",
        resource_type="membership",
        actor_user_id=user.id,
        workspace_id=workspace_id,
        resource_id=str(membership.id),
        detail=f"role={payload.role.value}",
    )
    db.commit()
    db.refresh(membership)
    return _member_response(membership)
