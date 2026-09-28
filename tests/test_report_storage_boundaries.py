"""SDK fault injection through production storage/rendering wrappers, no network."""

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from packages.reporting import generation


def storage(monkeypatch, *, exists=True, endpoint="https://storage.example.invalid"):
    client = MagicMock()
    client.bucket_exists.return_value = exists
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(generation, "Minio", factory)
    result = generation.MinioReportObjectStorage(
        endpoint_url=endpoint, access_key="synthetic", secret_key="unused", bucket="private"
    )
    return result, client, factory


@pytest.mark.parametrize("exists", [True, False])
def test_bucket_setup_and_tls_are_forwarded(monkeypatch, exists):
    _, client, factory = storage(monkeypatch, exists=exists)
    factory.assert_called_once_with(
        "storage.example.invalid", access_key="synthetic", secret_key="unused", secure=True
    )
    client.bucket_exists.assert_called_once_with("private")
    if exists:
        client.make_bucket.assert_not_called()
    else:
        client.make_bucket.assert_called_once_with("private")


@pytest.mark.parametrize("endpoint", ["file:///tmp/object", "ftp://example.invalid", "http://"])
def test_invalid_endpoint_does_not_construct_sdk(monkeypatch, endpoint):
    factory = MagicMock()
    monkeypatch.setattr(generation, "Minio", factory)
    with pytest.raises(ValueError, match="HTTP"):
        generation.MinioReportObjectStorage(
            endpoint_url=endpoint, access_key="synthetic", secret_key="unused", bucket="private"
        )
    factory.assert_not_called()


def test_upload_bytes_metadata_and_delete_use_private_bucket(monkeypatch):
    result, client, factory = storage(monkeypatch, endpoint="http://storage.example.invalid:9000")
    assert factory.call_args.kwargs["secure"] is False
    payload = b"synthetic report"
    result.put("reports/fixture.pdf", payload, "application/pdf")
    args, kwargs = client.put_object.call_args
    assert args[:2] == ("private", "reports/fixture.pdf")
    assert args[2].read() == payload
    assert kwargs == {"length": len(payload), "content_type": "application/pdf"}
    result.delete("reports/fixture.pdf")
    client.remove_object.assert_called_once_with("private", "reports/fixture.pdf")


@pytest.mark.parametrize("outcome", ["exact_limit", "too_large", "read_error"])
def test_download_bounds_and_always_releases_response(monkeypatch, outcome):
    result, client, _ = storage(monkeypatch)
    response = MagicMock()
    client.get_object.return_value = response
    response.read.return_value = b"1234" if outcome == "exact_limit" else b"12345"
    if outcome == "read_error":
        response.read.side_effect = OSError("synthetic storage failure")
        with pytest.raises(OSError):
            result.get("fixture", max_bytes=4)
    elif outcome == "too_large":
        with pytest.raises(ValueError, match="download limit"):
            result.get("fixture", max_bytes=4)
    else:
        assert result.get("fixture", max_bytes=4) == b"1234"
    client.get_object.assert_called_once_with("private", "fixture")
    response.read.assert_called_once_with(5)
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


def test_age_filter_skips_incomplete_metadata_and_includes_boundary(monkeypatch):
    result, client, _ = storage(monkeypatch)
    cutoff = datetime(2026, 9, 28, tzinfo=UTC)
    client.list_objects.return_value = [
        SimpleNamespace(object_name=None, last_modified=cutoff),
        SimpleNamespace(object_name="missing-date", last_modified=None),
        SimpleNamespace(object_name="boundary", last_modified=cutoff),
        SimpleNamespace(object_name="naive", last_modified=cutoff.replace(tzinfo=None)),
        SimpleNamespace(object_name="recent", last_modified=cutoff + timedelta(seconds=1)),
    ]
    assert list(result.list_older_than(cutoff)) == ["boundary", "naive"]
    client.list_objects.assert_called_once_with("private", prefix="reports/", recursive=True)


def test_pdf_missing_dependency_is_safe_retryable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(generation.ReportGenerationError) as error:
        generation.render_pdf("<p>synthetic</p>")
    assert error.value.code == "report.pdf_renderer_unavailable"
    assert error.value.retryable


@pytest.mark.parametrize("outcome", ["success", "render_failure", "file", "http"])
def test_pdf_wrapper_maps_failures_and_denies_external_fetches(monkeypatch, outcome):
    module = ModuleType("weasyprint")
    urls = ModuleType("weasyprint.urls")
    calls = []

    class URLFetchingError(Exception):
        pass

    def html(*, string, url_fetcher):
        calls.append(string)

        def write_pdf():
            if outcome in {"file", "http"}:
                url_fetcher("file:///synthetic-only" if outcome == "file" else "https://invalid")
            if outcome == "render_failure":
                raise OSError("synthetic renderer failure")
            return bytearray(b"%PDF-synthetic")

        return SimpleNamespace(write_pdf=write_pdf)

    module.HTML = html
    urls.URLFetchingError = URLFetchingError
    monkeypatch.setitem(sys.modules, "weasyprint", module)
    monkeypatch.setitem(sys.modules, "weasyprint.urls", urls)
    if outcome == "success":
        assert generation.render_pdf("fixture") == b"%PDF-synthetic"
    else:
        with pytest.raises(generation.ReportGenerationError) as error:
            generation.render_pdf("fixture")
        assert error.value.code == "report.pdf_render_failed" and error.value.retryable
        if outcome in {"file", "http"}:
            assert isinstance(error.value.__cause__, URLFetchingError)
    assert calls == ["fixture"]
