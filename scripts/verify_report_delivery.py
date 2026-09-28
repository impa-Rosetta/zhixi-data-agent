"""Isolated report delivery acceptance using synthetic test fixtures.

Seed/check run from the repo's development environment. Real Celery workers
read the exported SQLite fixture; production PostgreSQL migration and browser
acceptance are separate checks. No model provider call is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_analysis_report_service import (  # type: ignore[import-not-found]  # noqa: E402
    _payload,
    _trusted_source,
)

from apps.api.dependencies import get_current_user  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.routes import analysis_reports as routes  # noqa: E402
from apps.api.services.analysis_reports import create_report  # noqa: E402
from packages.agent_core.persistence import (  # noqa: E402
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportStatus,
)
from packages.platform_core.database import get_db  # noqa: E402
from packages.platform_core.models import Membership, User, WorkspaceRole  # noqa: E402
from packages.reporting.generation import MinioReportObjectStorage  # noqa: E402


def seed(path: Path, database_url: str | None = None) -> None:
    if database_url is None and path.exists():
        raise ValueError("Refusing to overwrite an existing fixture database")
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url) if database_url else None
    db, user, workspace, conversation, turn, _ = _trusted_source(engine)
    report = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-delivery-acceptance",
        payload=_payload(conversation, turn),
    )
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.ANALYST))
    db.commit()
    if database_url is None:
        with sqlite3.connect(path) as destination:
            db.connection().connection.driver_connection.backup(destination)
    print(json.dumps({"report_id": str(report.id), "database": "synthetic fixture"}))
    db.close()


def check(path: Path, output: Path, database_url: str | None = None) -> None:
    from fastapi.testclient import TestClient
    from minio import Minio
    from minio.error import S3Error

    if (database_url is None and not path.is_file()) or output.exists():
        raise ValueError("Fixture required; output must not already exist")
    engine = (
        create_engine(database_url)
        if database_url
        else create_engine(
            f"sqlite+pysqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
    )
    storage = MinioReportObjectStorage(
        endpoint_url="http://127.0.0.1:59005",
        access_key="report-fixture",
        secret_key="report-fixture-local-only",
        bucket="report-delivery-d5",
    )
    with Session(engine) as db:
        report = db.scalar(select(AnalysisReport))
        assert report is not None and report.status == AnalysisReportStatus.SUCCEEDED
        assert report.attempt_count == 1
        files = list(db.scalars(select(AnalysisReportFile)))
        assert len(files) == 3
        for item in files:
            content = storage.get(item.object_key, max_bytes=25_000_000)
            assert hashlib.sha256(content).hexdigest() == item.sha256_digest
        pdf_file = next(item for item in files if item.format.value == "pdf")
        anonymous = Minio("127.0.0.1:59005", secure=False)
        try:
            anonymous_response = anonymous.get_object("report-delivery-d5", pdf_file.object_key)
        except S3Error as exc:
            assert exc.code == "AccessDenied"
        else:
            anonymous_response.close()
            anonymous_response.release_conn()
            raise AssertionError("Anonymous storage download was allowed")
        user = db.get(User, report.created_by_user_id)
        assert user is not None
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        original_storage = routes._storage
        calls: list[int] = []

        def actual_storage() -> MinioReportObjectStorage:
            calls.append(1)
            return storage

        routes._storage = actual_storage
        url = f"/api/v1/workspaces/{report.workspace_id}/reports/{report.id}/files/pdf"
        try:
            with TestClient(app) as client:
                response = client.get(url)
                assert response.status_code == 200
                assert response.content.startswith(b"%PDF-")
                assert hashlib.sha256(response.content).hexdigest() == pdf_file.sha256_digest
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["content-disposition"].startswith("attachment;")
                count = len(calls)
                membership = db.scalar(
                    select(Membership).where(
                        Membership.user_id == user.id,
                        Membership.workspace_id == report.workspace_id,
                    )
                )
                assert membership is not None
                db.delete(membership)
                db.commit()
                denied = client.get(url)
                assert denied.status_code == 403
                assert len(calls) == count
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as handle:
                    handle.write(response.content)
        finally:
            routes._storage = original_storage
            app.dependency_overrides.clear()
        print(
            json.dumps(
                {
                    "formats": 3,
                    "sha256_verified": True,
                    "anonymous_denied": True,
                    "download_status": 200,
                    "revoked_status": 403,
                    "revoked_before_storage": True,
                    "attempt_count": report.attempt_count,
                    "pdf_bytes": len(response.content),
                }
            )
        )
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["seed", "check"])
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database-url", help="Isolated synthetic database only")
    args = parser.parse_args()
    if args.phase == "seed":
        seed(args.database.resolve(), args.database_url)
    elif args.output is not None:
        check(args.database.resolve(), args.output.resolve(), args.database_url)
    else:
        parser.error("--output is required for check")


if __name__ == "__main__":
    main()
