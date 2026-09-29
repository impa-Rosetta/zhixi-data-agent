import hashlib
import json

import pytest
from test_modeling_data import fixture

from packages.modeling.data import ModelDataError
from packages.modeling.snapshots import decode_training_snapshot, encode_training_snapshot


def test_snapshot_roundtrip_does_not_alias_mutable_source():
    source, spec = fixture()
    snapshot = encode_training_snapshot(spec, lambda _: source)
    restored = decode_training_snapshot(snapshot.content, snapshot.digest, spec, lambda _: source)
    assert restored.total_count == 40 and restored.rows[0] == (0.0, "A", 0.0)
    source.data["rows"][0][0] = 99
    assert restored.rows[0][0] == 0.0
    assert hashlib.sha256(snapshot.content).hexdigest() == snapshot.digest
    with pytest.raises(ModelDataError):
        decode_training_snapshot(snapshot.content, snapshot.digest, spec, lambda _: source)


def test_bad_digest_rejected_before_permission_loader():
    source, spec = fixture()
    snapshot = encode_training_snapshot(spec, lambda _: source)

    def unexpected(_):
        pytest.fail("corrupt bytes must not reach source reader")

    with pytest.raises(ModelDataError, match="model.snapshot_digest_mismatch"):
        decode_training_snapshot(snapshot.content + b"x", snapshot.digest, spec, unexpected)


def test_current_revocation_rejects_old_snapshot():
    source, spec = fixture()
    snapshot = encode_training_snapshot(spec, lambda _: source)

    def denied(_):
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        decode_training_snapshot(snapshot.content, snapshot.digest, spec, denied)


@pytest.mark.parametrize("change", ["extra", "spec", "evidence", "rows", "version"])
def test_rehashed_tampering_is_not_trusted(change):
    source, spec = fixture()
    snapshot = encode_training_snapshot(spec, lambda _: source)
    payload = json.loads(snapshot.content)
    if change == "extra":
        payload["path"] = "/unsafe"
    elif change == "spec":
        payload["spec"]["random_seed"] = 17
    elif change == "evidence":
        payload["evidence_id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "version":
        payload["version"] = 2
    else:
        payload["data"]["rows"][0][0] = 99
    content = json.dumps(payload).encode()
    with pytest.raises(ModelDataError):
        decode_training_snapshot(
            content, hashlib.sha256(content).hexdigest(), spec, lambda _: source
        )


@pytest.mark.parametrize("content", [b"{}", b"not json", b"\xff"])
def test_invalid_snapshot_format(content):
    source, spec = fixture()
    with pytest.raises(ModelDataError):
        decode_training_snapshot(
            content, hashlib.sha256(content).hexdigest(), spec, lambda _: source
        )
