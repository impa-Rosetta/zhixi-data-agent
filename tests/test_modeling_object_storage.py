import uuid

import pytest

import packages.modeling.object_storage as module
from packages.modeling.data import ModelDataError


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.closed = False
        self.released = False

    def read(self, length):
        return self.content[:length]

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinio:
    def __init__(self, endpoint, **kwargs):
        self.endpoint = endpoint
        self.options = kwargs
        self.objects = {}
        self.responses = []

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, stream, *, length, content_type):
        content = stream.read()
        assert len(content) == length
        self.objects[key] = (content, content_type)

    def get_object(self, bucket, key):
        response = FakeResponse(self.objects[key][0])
        self.responses.append(response)
        return response


@pytest.fixture
def storage(monkeypatch):
    fake = FakeMinio("ignored")
    monkeypatch.setattr(module, "Minio", lambda *args, **kwargs: fake)
    return module.MinioModelObjectStorage(
        endpoint_url="http://minio.internal:9000",
        access_key="test",
        secret_key="test",
        bucket="private",
    ), fake


def key(kind="snapshots", extension="json"):
    return f"modeling/{uuid.uuid4()}/{kind}/{uuid.uuid4()}/{'a' * 64}.{extension}"


def test_private_snapshot_and_model_roundtrip_and_close(storage):
    store, fake = storage
    for kind, extension, media_type in (
        ("snapshots", "json", "application/json"),
        ("models", "skops", "application/octet-stream"),
    ):
        object_key = key(kind, extension)
        store.put(object_key, b"example", media_type)
        assert store.get(object_key, max_bytes=7) == b"example"
    assert len(fake.responses) == 2
    assert all(response.closed and response.released for response in fake.responses)


@pytest.mark.parametrize("object_key", ["../secret", "reports/file", key("models", "json")])
def test_rejects_non_model_or_cross_kind_key_without_network(storage, object_key):
    store, fake = storage
    with pytest.raises(ModelDataError, match="model.invalid_object_key"):
        store.put(object_key, b"x", "application/json")
    assert fake.objects == {}


def test_rejects_wrong_media_and_overlarge_read_but_releases_response(storage):
    store, fake = storage
    object_key = key()
    with pytest.raises(ModelDataError, match="model.invalid_media_type"):
        store.put(object_key, b"x", "application/octet-stream")
    store.put(object_key, b"12345", "application/json")
    with pytest.raises(ModelDataError, match="model.object_too_large"):
        store.get(object_key, max_bytes=4)
    assert fake.responses[-1].closed and fake.responses[-1].released
