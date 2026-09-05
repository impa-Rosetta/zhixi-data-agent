"""Run the live API -> Outbox -> Worker M5 acceptance against Compose sample sources."""

import argparse
import json
import os
import time
from typing import Any, cast

import httpx


def require_success(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("Expected an object response")
    return value


def require_object_list(response: httpx.Response) -> list[dict[str, Any]]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("Expected a list of object responses")
    return cast(list[dict[str, Any]], value)


def wait_job(
    client: httpx.Client,
    *,
    workspace_id: str,
    job_id: str,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    path = f"/api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}"
    while time.monotonic() < deadline:
        job = require_success(client.get(path))
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            if job["status"] != "succeeded":
                raise RuntimeError(
                    f"Job {job_id} ended as {job['status']} ({job.get('error_code')})"
                )
            return job
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout_seconds} seconds")


def wait_initial_metadata(
    client: httpx.Client, *, workspace_id: str, source_id: str, timeout_seconds: int = 90
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    path = f"/api/v1/workspaces/{workspace_id}/data-sources/{source_id}/jobs"
    while time.monotonic() < deadline:
        jobs = require_object_list(client.get(path))
        completed = [
            item
            for item in jobs
            if item["job_type"] == "metadata_scan" and item["status"] == "succeeded"
        ]
        if completed:
            return completed[0]
        failures = [
            item
            for item in jobs
            if item["job_type"] == "metadata_scan" and item["status"] in {"failed", "cancelled"}
        ]
        if failures:
            raise RuntimeError(f"Initial metadata scan failed: {failures[0]}")
        time.sleep(1)
    raise TimeoutError("Initial metadata scan did not finish")


def wait_child_profile(
    client: httpx.Client,
    *,
    workspace_id: str,
    source_id: str,
    parent_job_id: str,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    path = f"/api/v1/workspaces/{workspace_id}/data-sources/{source_id}/jobs"
    while time.monotonic() < deadline:
        jobs = require_object_list(client.get(path))
        matches = [
            item
            for item in jobs
            if item["job_type"] == "profile_scan" and item["parent_job_id"] == parent_job_id
        ]
        if matches:
            return wait_job(
                client,
                workspace_id=workspace_id,
                job_id=matches[0]["id"],
                timeout_seconds=timeout_seconds,
            )
        time.sleep(1)
    raise TimeoutError("Profile task was not derived from metadata publication")


def accept_source(
    client: httpx.Client,
    *,
    workspace_id: str,
    source_type: str,
    host: str,
    port: int,
    schema_name: str,
    source_password: str,
) -> dict[str, Any]:
    base = f"/api/v1/workspaces/{workspace_id}/data-sources"
    created = require_success(
        client.post(
            base,
            json={
                "name": f"M5 {source_type} acceptance",
                "source_type": source_type,
                "host": host,
                "port": port,
                "database_name": "factory_demo",
                "tls_mode": "disable" if source_type == "postgresql" else "require",
                "credentials": {
                    "username": "zhixi_reader",
                    "password": source_password,
                },
            },
        )
    )
    serialized = json.dumps(created, ensure_ascii=False)
    if source_password in serialized or "zhixi_reader" in serialized:
        raise RuntimeError("Credential material leaked into create response")
    source_id = created["data_source"]["id"]
    wait_job(client, workspace_id=workspace_id, job_id=created["job"]["id"])
    wait_initial_metadata(client, workspace_id=workspace_id, source_id=source_id)
    snapshots = client.get(f"{base}/{source_id}/snapshots").json()
    if not snapshots or snapshots[0]["profiling_status"] != "disabled":
        raise RuntimeError("Default-off sampling invariant failed")
    policy = require_success(
        client.put(
            f"{base}/{source_id}/sampling-policy",
            json={
                "version": 0,
                "enabled": True,
                "schema_allowlist": [schema_name],
                "table_allowlist": [
                    {"schema_name": schema_name, "table_name": "production_orders"}
                ],
                "max_rows_per_table": 2,
                "max_values_per_column": 2,
                "max_value_chars": 64,
                "max_bytes_per_table": 4096,
                "max_bytes_per_job": 8192,
                "statement_timeout_seconds": 3,
            },
        )
    )
    if policy["enabled"] is not True:
        raise RuntimeError("Sampling policy was not enabled")
    metadata = require_success(
        client.post(
            f"{base}/{source_id}/scans",
            headers={"Idempotency-Key": f"m5-{source_type}-profile"},
            json={"schemas": [schema_name]},
        )
    )
    wait_job(client, workspace_id=workspace_id, job_id=metadata["id"])
    profile_job = wait_child_profile(
        client,
        workspace_id=workspace_id,
        source_id=source_id,
        parent_job_id=metadata["id"],
    )
    snapshot_id = profile_job["snapshot_id"]
    profiles = require_success(
        client.get(f"{base}/{source_id}/catalog/snapshots/{snapshot_id}/profiles")
    )
    counts = profiles["profile_counts"]
    if profiles["profiling_status"] != "succeeded" or counts["columns"] < 1:
        raise RuntimeError("Profile publication did not succeed")
    if counts["samples"] > counts["columns"] * 2 or counts["sample_bytes"] > 8192:
        raise RuntimeError("Profile budget was exceeded")
    return {
        "source_type": source_type,
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "profile_job_id": profile_job["id"],
        "profile_counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    admin_password = os.environ["M5_ADMIN_PASSWORD"]
    source_password = os.environ["M5_SOURCE_PASSWORD"]
    with httpx.Client(base_url=args.base_url, timeout=15) as client:
        tokens = require_success(
            client.post(
                "/api/v1/auth/bootstrap",
                json={
                    "email": "m5-acceptance@example.com",
                    "display_name": "M5 Acceptance",
                    "password": admin_password,
                    "workspace_name": "M5 Acceptance",
                    "workspace_slug": "m5-acceptance",
                },
            )
        )
        client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
        results = [
            accept_source(
                client,
                workspace_id=workspace_id,
                source_type="postgresql",
                host="source-postgres",
                port=5432,
                schema_name="public",
                source_password=source_password,
            ),
            accept_source(
                client,
                workspace_id=workspace_id,
                source_type="mysql",
                host="source-mysql",
                port=3306,
                schema_name="factory_demo",
                source_password=source_password,
            ),
        ]
        print(json.dumps({"workspace_id": workspace_id, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
