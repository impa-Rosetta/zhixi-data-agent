from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.audit import add_audit_event
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.rate_limit import LoginRateLimiter, get_login_rate_limiter
from packages.platform_core.models import (
    Membership,
    RefreshSession,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceRole,
)
from packages.platform_core.security import (
    hash_password,
    hash_refresh_token,
    issue_token_pair,
    verify_password,
)
from packages.platform_core.settings import get_settings
from packages.shared_contracts.auth import (
    BootstrapRequest,
    BootstrapStatusResponse,
    InvitationAcceptRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    WorkspaceSummary,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _response_and_session(db: DbSession, user: User) -> TokenResponse:
    settings = get_settings()
    pair = issue_token_pair(user.id, settings)
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=hash_refresh_token(pair.refresh_token),
            expires_at=pair.refresh_expires_at,
        )
    )
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=int((pair.access_expires_at - datetime.now(UTC)).total_seconds()),
    )


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(db: DbSession) -> BootstrapStatusResponse:
    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    return BootstrapStatusResponse(
        initialized=user_count > 0,
    )


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def bootstrap(payload: BootstrapRequest, db: DbSession) -> TokenResponse:
    if db.scalar(select(func.count()).select_from(User)) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Platform has already been initialized")
    user = User(
        email=payload.email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    workspace = Workspace(name=payload.workspace_name.strip(), slug=payload.workspace_slug)
    db.add_all([user, workspace])
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.SYSTEM_ADMIN))
    response = _response_and_session(db, user)
    add_audit_event(
        db,
        action="platform.bootstrap",
        outcome="success",
        resource_type="workspace",
        actor_user_id=user.id,
        workspace_id=workspace.id,
        resource_id=str(workspace.id),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Platform initialization conflict") from exc
    return response


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> TokenResponse:
    normalized_email = payload.email.strip().lower()
    limiter.check(f"{request.client.host if request.client else 'unknown'}:{normalized_email}")
    user = db.scalar(select(User).where(User.email == normalized_email))
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, payload.password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    response = _response_and_session(db, user)
    add_audit_event(
        db,
        action="auth.login",
        outcome="success",
        resource_type="user",
        actor_user_id=user.id,
        resource_id=str(user.id),
    )
    db.commit()
    return response


@router.post(
    "/accept-invitation", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
def accept_invitation(payload: InvitationAcceptRequest, db: DbSession) -> TokenResponse:
    now = datetime.now(UTC)
    invitation = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.token_hash == hash_refresh_token(payload.invite_token)
        )
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or _as_utc(invitation.expires_at) <= now
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation")
    if db.scalar(select(User).where(User.email == invitation.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User already exists")
    user = User(
        email=invitation.email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    db.add(Membership(workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = now
    response = _response_and_session(db, user)
    add_audit_event(
        db,
        action="member.invitation.accept",
        outcome="success",
        resource_type="workspace_invitation",
        actor_user_id=user.id,
        workspace_id=invitation.workspace_id,
        resource_id=str(invitation.id),
    )
    db.commit()
    return response


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    now = datetime.now(UTC)
    old_session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if (
        old_session is None
        or old_session.revoked_at is not None
        or _as_utc(old_session.expires_at) <= now
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    user = db.get(User, old_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inactive or missing user")
    old_session.revoked_at = now
    response = _response_and_session(db, user)
    new_session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(response.refresh_token)
        )
    )
    if new_session is not None:
        old_session.replaced_by_id = new_session.id
    db.commit()
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: DbSession) -> None:
    refresh_session = db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if refresh_session is not None and refresh_session.revoked_at is None:
        refresh_session.revoked_at = datetime.now(UTC)
        db.commit()


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        workspaces=[
            WorkspaceSummary(
                id=membership.workspace.id,
                name=membership.workspace.name,
                slug=membership.workspace.slug,
                role=membership.role,
            )
            for membership in user.memberships
        ],
    )
