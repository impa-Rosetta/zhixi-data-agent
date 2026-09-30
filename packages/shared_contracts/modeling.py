"""Public, non-sensitive modeling task status contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    attempt_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    model_version_id: uuid.UUID | None = None
    error_code: str | None = None
