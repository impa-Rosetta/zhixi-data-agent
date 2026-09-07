import enum
import uuid
from dataclasses import dataclass

from packages.platform_core.models import WorkspaceRole


class Action(enum.StrEnum):
    WORKSPACE_READ = "workspace.read"
    MEMBER_READ = "member.read"
    MEMBER_INVITE = "member.invite"
    MEMBER_ROLE_UPDATE = "member.role.update"
    DATA_SOURCE_MANAGE = "data_source.manage"
    CATALOG_READ = "catalog.read"
    SEMANTIC_READ = "semantic.read"
    SEMANTIC_MANAGE = "semantic.manage"
    ANALYSIS_RUN = "analysis.run"
    AUDIT_READ = "audit.read"


_ROLE_ACTIONS: dict[WorkspaceRole, frozenset[Action]] = {
    WorkspaceRole.SYSTEM_ADMIN: frozenset(Action),
    WorkspaceRole.WORKSPACE_ADMIN: frozenset(Action),
    WorkspaceRole.DATA_ADMIN: frozenset(
        {
            Action.WORKSPACE_READ,
            Action.MEMBER_READ,
            Action.DATA_SOURCE_MANAGE,
            Action.CATALOG_READ,
            Action.ANALYSIS_RUN,
        }
    ),
    WorkspaceRole.ANALYST: frozenset(
        {Action.WORKSPACE_READ, Action.CATALOG_READ, Action.SEMANTIC_READ, Action.ANALYSIS_RUN}
    ),
    WorkspaceRole.AUDITOR: frozenset(
        {
            Action.WORKSPACE_READ,
            Action.MEMBER_READ,
            Action.CATALOG_READ,
            Action.SEMANTIC_READ,
            Action.AUDIT_READ,
        }
    ),
}


@dataclass(frozen=True)
class PolicyRequest:
    actor_user_id: uuid.UUID
    actor_workspace_id: uuid.UUID
    resource_workspace_id: uuid.UUID
    role: WorkspaceRole
    action: Action


def is_allowed(request: PolicyRequest) -> bool:
    if request.actor_workspace_id != request.resource_workspace_id:
        return False
    return request.action in _ROLE_ACTIONS[request.role]
