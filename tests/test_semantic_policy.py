from packages.platform_core.models import WorkspaceRole
from packages.platform_core.policy import Action, is_allowed
from tests.test_policy import request


def test_semantic_model_permissions_follow_least_privilege() -> None:
    assert is_allowed(request(WorkspaceRole.WORKSPACE_ADMIN, Action.SEMANTIC_MANAGE))
    assert is_allowed(request(WorkspaceRole.ANALYST, Action.SEMANTIC_READ))
    assert is_allowed(request(WorkspaceRole.AUDITOR, Action.SEMANTIC_READ))
    assert not is_allowed(request(WorkspaceRole.ANALYST, Action.SEMANTIC_MANAGE))
    assert not is_allowed(request(WorkspaceRole.AUDITOR, Action.SEMANTIC_MANAGE))
    assert not is_allowed(request(WorkspaceRole.DATA_ADMIN, Action.SEMANTIC_MANAGE))
