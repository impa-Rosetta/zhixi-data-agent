"""Owned isolated SQL/runtime/report acceptance. Fixed model responses, no paid LLM.

Run only in infra/acceptance/advanced-stack.compose.yaml. Platform and source
hostnames are pinned; never point this harness at the user's existing database.
"""

from __future__ import annotations

import json
import statistics
import time

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from apps.api.services.analysis_conversations import create_conversation, send_conversation_message
from apps.api.services.analysis_runs import get_run_view
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.contracts import Intent
from packages.agent_core.conversation_runtime import synchronize_conversation_after_run
from packages.agent_core.persistence import AnalysisRun, AnalysisTurn
from packages.evaluation.postgres_draft_adapter import FIXTURE_URL, _seed
from packages.evaluation.quality_metric_fixture import EXTRA_QUALITY_MAPPINGS
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import get_engine
from packages.platform_core.models import Membership, WorkspaceRole
from packages.platform_core.security import hash_password
from packages.platform_core.settings import get_settings
from packages.shared_contracts.agents import (
    CreateAnalysisConversationRequest,
    SendAnalysisConversationMessageRequest,
)

PASSWORD = "advanced-fixture-local-only"


def gateway(output: dict[str, object] | None) -> FakeGateway:
    return FakeGateway(
        []
        if output is None
        else [
            GatewayResponse(
                "offline-advanced-acceptance",
                "fake",
                json.dumps(output, ensure_ascii=False),
                None,
                (),
                "stop",
                GatewayUsage(model_calls=0),
            )
        ]
    )


def main() -> None:
    settings = get_settings()
    if "@platform-advanced:5432/advanced" not in settings.database_url:
        raise ValueError("acceptance.only_owned_platform_allowed")
    if settings.deepseek_api_key.get_secret_value():
        raise ValueError("acceptance.paid_model_must_be_disabled")
    source_engine = create_engine(FIXTURE_URL)
    with source_engine.begin() as connection:
        exists = connection.scalar(text("SELECT to_regnamespace('advanced_fixture')"))
        if exists:
            raise ValueError("acceptance.refuse_existing_fixture")
        connection.execute(text("CREATE SCHEMA advanced_fixture"))
        connection.execute(
            text(
                "CREATE TABLE advanced_fixture.quality_inspections "
                "(inspected_quantity bigint, qualified_quantity bigint, "
                "defect_quantity bigint, scrap_quantity bigint, "
                "rework_quantity bigint, first_pass_quantity bigint, "
                "inspected_at timestamptz)"
            )
        )
        for index in range(12):
            defect = index + 2 if index < 11 else 60
            rework = index + 1 if index < 11 else 55
            connection.execute(
                text(
                    "INSERT INTO advanced_fixture.quality_inspections "
                    "VALUES (100, :qualified, :defect, 0, :rework, :qualified, :at)"
                ),
                {
                    "qualified": 100 - defect,
                    "defect": defect,
                    "rework": rework,
                    "at": f"2026-09-{index + 1:02d}T09:00:00Z",
                },
            )
        connection.execute(text("GRANT USAGE ON SCHEMA advanced_fixture TO zhixi_reader"))
        connection.execute(
            text("GRANT SELECT ON advanced_fixture.quality_inspections TO zhixi_reader")
        )
    with Session(get_engine()) as db:
        user, workspace = _seed(
            db, source_schema="advanced_fixture", extra_mappings=EXTRA_QUALITY_MAPPINGS
        )
        user.password_hash = hash_password(PASSWORD)
        db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.ANALYST))
        db.commit()
        base_intent: dict[str, object] = {
            "task_type": "correlation",
            "goal": "按天分析不良率与返工率的相关性",
            "metrics": ["不良率", "返工率"],
            "dimensions": ["检验时间"],
            "confidence": 1,
        }
        anomaly_intent = {
            **base_intent,
            "task_type": "anomaly_detection",
            "goal": "按天检查不良率的异常",
            "metrics": ["不良率"],
        }
        Intent.model_validate(base_intent)
        Intent.model_validate(anomaly_intent)
        phases: list[tuple[str, dict[str, object] | None]] = [
            (str(base_intent["goal"]), base_intent),
            ("改用Spearman重新计算", {"mode": "patch", "patch": {"analysis_method": "spearman"}}),
            ("解释这个结果", None),
            ("新主题：按天检查不良率的异常", anomaly_intent),
            ("解释这个结果", None),
        ]
        conversation = create_conversation(
            db,
            workspace_id=workspace.id,
            actor_user_id=user.id,
            idempotency_key="advanced-acceptance",
            payload=CreateAnalysisConversationRequest(message=phases[0][0]),
        )
        run_ids, selected_turns, outcomes = [], [], []
        for index, (message, output) in enumerate(phases):
            if index:
                send_conversation_message(
                    db,
                    workspace_id=workspace.id,
                    actor_user_id=user.id,
                    conversation_id=conversation.id,
                    idempotency_key=f"advanced-turn-{index}",
                    payload=SendAnalysisConversationMessageRequest(message=message),
                )
            turn = db.scalar(
                select(AnalysisTurn).where(
                    AnalysisTurn.conversation_id == conversation.id,
                    AnalysisTurn.sequence == index + 1,
                )
            )
            assert turn and turn.analysis_run_id
            db.commit()
            offline = gateway(output)
            run_analysis(db, run_id=turn.analysis_run_id, gateway=offline)
            synchronize_conversation_after_run(db, run_id=turn.analysis_run_id)
            db.commit()
            view = get_run_view(db, workspace_id=workspace.id, run_id=turn.analysis_run_id)
            assert view.run.status == "completed", (index, view.run.error_code)
            assert view.run.model_calls == 0
            query = next(
                (item for item in view.artifacts if item.artifact_type == "query_result"), None
            )
            if query:
                assert query.summary["row_count"] == 12 and query.summary["truncated"] is False
                selected_turns.append(str(turn.id))
            result = next(
                (
                    item
                    for item in view.artifacts
                    if item.artifact_type in {"correlation_result", "anomaly_result"}
                ),
                None,
            )
            if index in {0, 1, 3}:
                assert result is not None and query is not None
            if result and index == 0:
                oracle = statistics.correlation([*range(2, 13), 60], [*range(1, 12), 55])
                assert abs(float(str(result.summary["coefficient"])) - oracle) < 1e-12
            if result and index == 1:
                assert (
                    result.summary["method"] == "spearman" and result.summary["coefficient"] == 1.0
                )
            if result and index == 3:
                assert result.summary["lower_bound"] == -3.5
                assert result.summary["upper_bound"] == 18.5
                assert query is not None
                columns = query.summary["columns"]
                rows = query.summary["rows"]
                assert isinstance(columns, list) and isinstance(rows, list)
                field_index = columns.index("defect_rate")
                candidates = [
                    position
                    for position, row in enumerate(rows)
                    if isinstance(row, list) and float(str(row[field_index])) == 60
                ]
                assert len(candidates) == 1
                assert result.summary["anomalies"] == [
                    {"row_index": candidates[0], "value": 60.0, "direction": "above"}
                ]
            outcomes.append(
                {
                    "turn": index + 1,
                    "status": view.run.status,
                    "tool_calls": [item.tool_name for item in view.tool_calls],
                }
            )
            run_ids.append(str(view.run.id))
        with httpx.Client(base_url="http://api-advanced:8000", timeout=20) as client:
            login = client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
            )
            login.raise_for_status()
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            prefix = f"/api/v1/workspaces/{workspace.id}"
            response = client.post(
                prefix + "/reports",
                headers={"Idempotency-Key": "advanced-report"},
                json={
                    "conversation_id": str(conversation.id),
                    "turn_ids": selected_turns,
                    "title": "高级分析联合验收（模拟数据）",
                },
            )
            response.raise_for_status()
            report_id = response.json()["id"]
            print(
                json.dumps(
                    {
                        "workspace_id": str(workspace.id),
                        "conversation_id": str(conversation.id),
                        "report_id": report_id,
                        "turns": outcomes,
                        "model_calls": 0,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                result_response = client.get(prefix + f"/reports/{report_id}")
                result_response.raise_for_status()
                report = result_response.json()
                if report["status"] == "succeeded":
                    break
                assert report["status"] != "failed", report["error_code"]
                time.sleep(1)
            else:
                raise TimeoutError("report did not complete in 50 seconds")
            for format_name in ("markdown", "html", "pdf"):
                download = client.get(prefix + f"/reports/{report_id}/files/{format_name}")
                download.raise_for_status()
                assert len(download.content) > 100
                if format_name == "html":
                    assert b"<svg" in download.content and b'fill="#dc4c64"' in download.content
                if format_name == "pdf":
                    assert download.content.startswith(b"%PDF-")
            print(
                json.dumps(
                    {
                        "report_status": "succeeded",
                        "formats_downloaded": 3,
                        "report_attempt_count": report["attempt_count"],
                        "conversation_id": str(conversation.id),
                        "model_calls": 0,
                    }
                ),
                flush=True,
            )
            assert all(run.model_calls == 0 for run in db.scalars(select(AnalysisRun)))


if __name__ == "__main__":
    main()
