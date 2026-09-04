import uuid

from packages.platform_core.models import WorkspaceRole
from packages.platform_core.policy import Action, PolicyRequest, is_allowed


def request(role: WorkspaceRole, action: Action, *, cross_workspace: bool = False) -> PolicyRequest:
    workspace_id = uuid.uuid4()
    return PolicyRequest(
        actor_user_id=uuid.uuid4(),
        actor_workspace_id=workspace_id,
        resource_workspace_id=uuid.uuid4() if cross_workspace else workspace_id,
        role=role,
        action=action,
    )


def test_workspace_admin_can_manage_members() -> None:
    assert is_allowed(request(WorkspaceRole.WORKSPACE_ADMIN, Action.MEMBER_INVITE))
    assert is_allowed(request(WorkspaceRole.WORKSPACE_ADMIN, Action.MEMBER_ROLE_UPDATE))


def test_analyst_cannot_manage_members() -> None:
    assert not is_allowed(request(WorkspaceRole.ANALYST, Action.MEMBER_INVITE))


def test_cross_workspace_access_is_always_denied() -> None:
    assert not is_allowed(
        request(WorkspaceRole.SYSTEM_ADMIN, Action.WORKSPACE_READ, cross_workspace=True)
    )
