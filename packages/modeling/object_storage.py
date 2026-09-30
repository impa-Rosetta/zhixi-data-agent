"""Private MinIO storage adapter for immutable modeling snapshots and files."""

from __future__ import annotations

import io
import re
from urllib.parse import urlparse

from minio import Minio

from packages.modeling.contracts import MAX_MODEL_BYTES
from packages.modeling.data import ModelDataError

_UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
_KEY = re.compile(
    rf"modeling/{_UUID}/(?:snapshots|models)/{_UUID}/[0-9a-f]{{64}}\.(?:json|skops)\Z"
)


class MinioModelObjectStorage:
    """No browser URL, presigned link or arbitrary user-supplied object path."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        parsed = urlparse(endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("S3 endpoint must be an HTTP(S) URL")
        self._client = Minio(
            parsed.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    @staticmethod
    def _validate_key(key: str) -> None:
        if not _KEY.fullmatch(key):
            raise ModelDataError("model.invalid_object_key")
        kind = key.split("/")[2]
        if (kind == "snapshots") != key.endswith(".json"):
            raise ModelDataError("model.invalid_object_key")

    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        self._validate_key(object_key)
        if not content or len(content) > MAX_MODEL_BYTES:
            raise ModelDataError("model.object_too_large")
        expected = (
            "application/json" if object_key.endswith(".json") else "application/octet-stream"
        )
        if media_type != expected:
            raise ModelDataError("model.invalid_media_type")
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=expected,
        )

    def get(self, object_key: str, *, max_bytes: int) -> bytes:
        self._validate_key(object_key)
        if max_bytes < 1 or max_bytes > MAX_MODEL_BYTES:
            raise ModelDataError("model.invalid_object_limit")
        response = self._client.get_object(self._bucket, object_key)
        try:
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ModelDataError("model.object_too_large")
            return bytes(content)
        finally:
            response.close()
            response.release_conn()
