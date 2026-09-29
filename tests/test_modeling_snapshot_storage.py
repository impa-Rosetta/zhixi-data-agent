import uuid

import pytest
from test_modeling_data import fixture

from packages.modeling.data import ModelDataError
from packages.modeling.snapshot_storage import read_training_snapshot, store_training_snapshot


class Storage:
    def __init__(self):
        self.objects = {}
        self.reads = 0

    def put(self, key, content, media_type):
        assert media_type == "application/json"
        self.objects[key] = content

    def get(self, key, *, max_bytes):
        self.reads += 1
        return self.objects[key]


def test_stored_snapshot_roundtrip_and_unique_keys():
    source, spec = fixture()
    storage, workspace = Storage(), uuid.uuid4()
    first = store_training_snapshot(storage, workspace, spec, lambda _: source)
    second = store_training_snapshot(storage, workspace, spec, lambda _: source)
    assert first.digest == second.digest and first.object_key != second.object_key
    result = read_training_snapshot(storage, workspace, first, spec, lambda _: source)
    assert result.total_count == 40 and len(result.rows) == 40


def test_cross_workspace_denied_before_storage_read():
    source, spec = fixture()
    storage, workspace = Storage(), uuid.uuid4()
    receipt = store_training_snapshot(storage, workspace, spec, lambda _: source)
    with pytest.raises(ModelDataError, match="policy.denied"):
        read_training_snapshot(storage, uuid.uuid4(), receipt, spec, lambda _: source)
    assert storage.reads == 0


def test_revoked_user_does_not_fetch_plaintext():
    source, spec = fixture()
    storage, workspace = Storage(), uuid.uuid4()
    receipt = store_training_snapshot(storage, workspace, spec, lambda _: source)

    def denied(_):
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        read_training_snapshot(storage, workspace, receipt, spec, denied)
    assert storage.reads == 0


def test_corrupt_object_is_rejected():
    source, spec = fixture()
    storage, workspace = Storage(), uuid.uuid4()
    receipt = store_training_snapshot(storage, workspace, spec, lambda _: source)
    storage.objects[receipt.object_key] += b"x"
    with pytest.raises(ModelDataError, match="model.snapshot_size_mismatch"):
        read_training_snapshot(storage, workspace, receipt, spec, lambda _: source)
