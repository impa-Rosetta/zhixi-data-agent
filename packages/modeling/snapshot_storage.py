"""Code-owned object keys for internal training snapshots, no user paths."""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from packages.modeling.contracts import MAX_MODEL_BYTES, Digest, ModelSpec
from packages.modeling.data import ModelDataError, PreparedTrainingData
from packages.modeling.snapshots import (
    SourceLoader,
    decode_training_snapshot,
    encode_training_snapshot,
)


class SnapshotObjectStorage(Protocol):
    def put(self, object_key: str, content: bytes, media_type: str) -> None: ...

    def get(self, object_key: str, *, max_bytes: int) -> bytes: ...


class SnapshotReceipt(BaseModel):
    """Must be stored server-side; a receipt is not authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: uuid.UUID
    snapshot_id: uuid.UUID
    digest: Digest
    size_bytes: StrictInt = Field(ge=1, le=MAX_MODEL_BYTES)

    @property
    def object_key(self) -> str:
        return f"modeling/{self.workspace_id}/snapshots/{self.snapshot_id}/{self.digest}.json"


def store_training_snapshot(
    storage: SnapshotObjectStorage, workspace_id: uuid.UUID, spec: ModelSpec, loader: SourceLoader
) -> SnapshotReceipt:
    snapshot = encode_training_snapshot(spec, loader)
    receipt = SnapshotReceipt(
        workspace_id=workspace_id,
        snapshot_id=uuid.uuid4(),
        digest=snapshot.digest,
        size_bytes=len(snapshot.content),
    )
    storage.put(receipt.object_key, snapshot.content, "application/json")
    return receipt


def read_training_snapshot(
    storage: SnapshotObjectStorage,
    workspace_id: uuid.UUID,
    receipt: SnapshotReceipt,
    spec: ModelSpec,
    loader: SourceLoader,
) -> PreparedTrainingData:
    if receipt.workspace_id != workspace_id:
        raise ModelDataError("policy.denied")
    # Validate current authority before obtaining stored plaintext, then validate again
    # in decode to reject changes occurring during storage access.
    from packages.modeling.data import prepare_training_data

    prepare_training_data(spec, loader)
    content = storage.get(receipt.object_key, max_bytes=MAX_MODEL_BYTES)
    if len(content) != receipt.size_bytes:
        raise ModelDataError("model.snapshot_size_mismatch")
    return decode_training_snapshot(content, receipt.digest, spec, loader)
