import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from packages.platform_core.database import Base


class SemanticModelStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SemanticVersionStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


class SemanticModel(Base):
    __tablename__ = "semantic_models"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_semantic_model_workspace_name"),
        Index("ix_semantic_model_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SemanticModelStatus] = mapped_column(
        Enum(
            SemanticModelStatus,
            name="semantic_model_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=SemanticModelStatus.DRAFT,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "semantic_model_versions.id",
            name="fk_semantic_model_active_version",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SemanticModelVersion(Base):
    __tablename__ = "semantic_model_versions"
    __table_args__ = (
        UniqueConstraint("semantic_model_id", "revision", name="uq_semantic_model_revision"),
        Index("ix_semantic_version_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    semantic_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("semantic_models.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[SemanticVersionStatus] = mapped_column(
        Enum(
            SemanticVersionStatus,
            name="semantic_version_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=SemanticVersionStatus.DRAFT,
    )
    document: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    content_digest: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
