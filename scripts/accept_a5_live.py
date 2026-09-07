"""Run the live A5 error matrix against the deployed Compose stack."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any, cast

import httpx

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def require_object(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("Expected an object response")
    return cast(dict[str, Any], value)


def wait_job(
    client: httpx.Client,
    *,
    workspace_id: str,
    job_id: str,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    path = f"/api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}"
    while time.monotonic() < deadline:
        job = require_object(client.get(path))
        if job["status"] in TERMINAL_STATUSES:
            return job
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout_seconds} seconds")


def source_payload(
    *,
    name: str,
    host: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "source_type": "mysql",
        "host": host,
        "port": 3306,
        "database_name": "factory_demo",
        "tls_mode": "require",
        "credentials": {"username": username, "password": password},
    }


def create_and_wait(
    client: httpx.Client,
    *,
    base: str,
    workspace_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    created = require_object(client.post(base, json=payload))
    serialized = json.dumps(created, ensure_ascii=False)
    credentials = cast(dict[str, str], payload["credentials"])
    if credentials["password"] in serialized or credentials["username"] in serialized:
        raise RuntimeError("Credential material leaked into create response")
    job = wait_job(
        client,
        workspace_id=workspace_id,
        job_id=cast(dict[str, Any], created["job"])["id"],
    )
    return created, job


def delete_source(client: httpx.Client, *, base: str, source_id: str) -> None:
    detail_response = client.get(f"{base}/{source_id}")
    if detail_response.status_code == 404:
        return
    detail = require_object(detail_response)
    response = client.delete(f"{base}/{source_id}", params={"version": detail["version"]})
    if response.status_code not in {204, 404}:
        response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    admin_password = os.environ["A5_ADMIN_PASSWORD"]
    reader_password = os.environ["A5_READER_PASSWORD"]
    writer_password = os.environ["A5_WRITER_PASSWORD"]
    suffix = uuid.uuid4().hex[:8]
    created_ids: list[str] = []
    results: dict[str, Any] = {}

    with httpx.Client(base_url=args.base_url, timeout=15) as client:
        tokens = require_object(
            client.post(
                "/api/v1/auth/login",
                json={"email": "demo@zhixi.local", "password": admin_password},
            )
        )
        client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        me = require_object(client.get("/api/v1/auth/me"))
        workspace_id = cast(list[dict[str, Any]], me["workspaces"])[0]["id"]
        base = f"/api/v1/workspaces/{workspace_id}/data-sources"

        cases = [
            (
                "authentication",
                source_payload(
                    name=f"A5 wrong password {suffix}",
                    host="source-mysql",
                    username="zhixi_reader",
                    password="definitely-wrong-local-password",
                ),
                {"connector.authentication_failed"},
            ),
            (
                "read_only",
                source_payload(
                    name=f"A5 writer rejection {suffix}",
                    host="source-mysql",
                    username="zhixi_writer",
                    password=writer_password,
                ),
                {"connector.read_only_required"},
            ),
            (
                "timeout",
                source_payload(
                    name=f"A5 timeout {suffix}",
                    host="172.19.0.250",
                    username="zhixi_reader",
                    password=reader_password,
                ),
                {"connector.connection_timeout", "connector.connection_failed"},
            ),
        ]

        try:
            for label, payload, expected_codes in cases:
                created, job = create_and_wait(
                    client,
                    base=base,
                    workspace_id=workspace_id,
                    payload=payload,
                )
                source_id = cast(dict[str, Any], created["data_source"])["id"]
                created_ids.append(source_id)
                if job["status"] != "failed" or job["error_code"] not in expected_codes:
                    raise RuntimeError(
                        f"{label} case returned {job['status']} / {job['error_code']}"
                    )
                results[label] = {
                    "status": job["status"],
                    "error_code": job["error_code"],
                    "terminal_progress": job.get("progress"),
                }

            reuse_name = f"A5 reusable source {suffix}"
            correct = source_payload(
                name=reuse_name,
                host="source-mysql",
                username="zhixi_reader",
                password=reader_password,
            )
            first, first_job = create_and_wait(
                client,
                base=base,
                workspace_id=workspace_id,
                payload=correct,
            )
            first_source = cast(dict[str, Any], first["data_source"])
            first_id = first_source["id"]
            created_ids.append(first_id)
            if first_job["status"] != "succeeded":
                raise RuntimeError(f"First reusable source failed: {first_job['error_code']}")

            updated = require_object(
                client.patch(
                    f"{base}/{first_id}",
                    json={"version": first_source["version"], "description": "A5 live fixture"},
                )
            )
            stale = client.patch(
                f"{base}/{first_id}",
                json={"version": first_source["version"], "description": "stale write"},
            )
            if stale.status_code != 409:
                raise RuntimeError(f"Expected version conflict, got {stale.status_code}")
            stale_value = stale.json()
            if not isinstance(stale_value, dict):
                raise RuntimeError("Expected an object conflict response")
            stale_body = cast(dict[str, Any], stale_value)
            results["version_conflict"] = {
                "status": stale.status_code,
                "error_code": cast(dict[str, Any], stale_body["detail"])["code"],
            }

            deleted = client.delete(
                f"{base}/{first_id}",
                params={"version": updated["version"]},
            )
            if deleted.status_code != 204:
                deleted.raise_for_status()
            created_ids.remove(first_id)

            second, second_job = create_and_wait(
                client,
                base=base,
                workspace_id=workspace_id,
                payload=correct,
            )
            second_id = cast(dict[str, Any], second["data_source"])["id"]
            created_ids.append(second_id)
            if second_job["status"] != "succeeded" or second_id == first_id:
                raise RuntimeError("Soft-deleted source name was not safely reusable")
            results["soft_delete_name_reuse"] = {
                "status": "succeeded",
                "new_resource_created": True,
            }
        finally:
            for source_id in reversed(created_ids):
                delete_source(client, base=base, source_id=source_id)

    print(json.dumps({"workspace_id": workspace_id, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
