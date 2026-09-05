import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.platform_core.models import WorkspaceRole


class BootstrapRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=120)
    workspace_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("Invalid email address")
        return value


class BootstrapStatusResponse(BaseModel):
    initialized: bool


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class LogoutRequest(RefreshRequest):
    pass


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class WorkspaceSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: WorkspaceRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    workspaces: list[WorkspaceSummary]


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: WorkspaceRole
    created_at: datetime


class MemberCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: WorkspaceRole


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: WorkspaceRole
    expires_at: datetime
    invite_token: str


class InvitationAcceptRequest(BaseModel):
    invite_token: str = Field(min_length=32, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class MemberRoleRequest(BaseModel):
    role: WorkspaceRole
