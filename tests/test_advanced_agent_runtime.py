import uuid

import pytest
from sqlalchemy import select
from test_advanced_analysis_sources import source_context as source_context

from apps.api.services.analysis_runs import create_run
from apps.worker.analysis_runtime import _complete_verified_result_explanation, run_analysis
from packages.agent_core.contracts import Binding, Intent
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisMessage,
    AnalysisRunStatus,
    AnalysisStepStatus,
    AnalysisToolCall,
)
from packages.model_gateway import FakeGateway
from packages.shared_contracts.agents import CreateAnalysisRunRequest


def prepare(context, task: str):
    db, _, _, records = context
    run = records["run"]
    metrics = ("x", "y") if task == "correlation" else ("y",)
    intent = Intent(
        task_type=task, goal="按天分析这些数据", metrics=metrics, dimensions=("日期",), confidence=1
    )
    binding = Binding(
        semantic_model_id=str(records["model"].id),
        semantic_version_id=str(records["version"].id),
        snapshot_ids=(str(records["snapshot"].id),),
        metric_keys=metrics,
        dimension_keys=("day",),
        time_dimension_key="day",
        confidence=1,
    )
    run.status = AnalysisRunStatus.QUEUED
    run.context = {
        **run.context,
        "intent": intent.model_dump(mode="json"),
        "binding": binding.model_dump(mode="json"),
    }
    db.commit()
    return db, run, dict(records["artifact"].summary)


@pytest.mark.parametrize(
    "task,kind,chart_type",
    [
        ("correlation", "correlation_result", "scatter"),
        ("anomaly_detection", "anomaly_result", "line"),
    ],
)
def test_durable_runtime_invokes_verified_tool_and_persists_chart_lineage(
    source_context, task, kind, chart_type
) -> None:
    db, run, data = prepare(source_context, task)
    run.context = {
        **run.context,
        "intent": {**run.context["intent"], "goal": "按天分析这些数据" * 40},
    }
    db.commit()
    run_analysis(db, run_id=run.id, gateway=FakeGateway([]), metric_executor=lambda *_: data)
    db.refresh(run)
    assert run.status is AnalysisRunStatus.COMPLETED, run.error_code
    artifact = db.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run.id, AnalysisArtifact.artifact_type == kind
        )
    )
    assert artifact is not None
    assert artifact.summary["sample_count"] == 10
    chart = db.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.run_id == run.id, AnalysisArtifact.artifact_type == "chart_spec"
        )
    )
    assert chart is not None and chart.summary["chart_type"] == chart_type
    assert len(chart.summary["title"]) == 200
    dataset = db.get(AnalysisArtifact, uuid.UUID(chart.summary["source_artifact_id"]))
    assert dataset.artifact_type == "visualization_data"
    assert dataset.summary["analysis_artifact_id"] == str(artifact.id)
    call = db.scalar(
        select(AnalysisToolCall).where(
            AnalysisToolCall.run_id == run.id,
            AnalysisToolCall.tool_name == "analysis.correlate"
            if task == "correlation"
            else AnalysisToolCall.tool_name == "analysis.detect_anomaly",
        )
    )
    assert call.status is AnalysisStepStatus.SUCCEEDED
    assert call.tool_version == "1.1.0"
    messages = db.scalars(
        select(AnalysisMessage).where(
            AnalysisMessage.run_id == run.id, AnalysisMessage.role == "assistant"
        )
    ).all()
    assert any(
        "因果" in item.content if task == "correlation" else "异常候选" in item.content
        for item in messages
    )


def test_advanced_runtime_refuses_tampered_evidence_instead_of_presenting_a_result(
    source_context,
) -> None:
    db, run, data = prepare(source_context, "correlation")
    data["evidence_digest"] = "0" * 64
    run_analysis(db, run_id=run.id, gateway=FakeGateway([]), metric_executor=lambda *_: data)
    db.refresh(run)
    assert run.status is AnalysisRunStatus.FAILED
    assert run.error_code == "analysis.digest_mismatch"
    assert not db.scalar(
        select(AnalysisArtifact.id).where(
            AnalysisArtifact.run_id == run.id,
            AnalysisArtifact.artifact_type == "correlation_result",
        )
    )


def test_explanation_rechecks_and_explains_actual_advanced_result(source_context) -> None:
    db, run, data = prepare(source_context, "correlation")
    run_analysis(db, run_id=run.id, gateway=FakeGateway([]), metric_executor=lambda *_: data)
    user, workspace = source_context[1:3]
    response = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="explain",
        payload=CreateAnalysisRunRequest(message="解释这个结果"),
    )
    explanation = db.get(type(run), response.id)
    explanation.status = AnalysisRunStatus.RUNNING
    explanation.context = {
        **explanation.context,
        "previous_run_id": str(run.id),
        "conversation_context": {
            "last_result": {"artifact_id": run.context["artifact_id"], "row_count": 10}
        },
    }
    db.commit()
    _complete_verified_result_explanation(
        db, explanation, Intent.model_validate(run.context["intent"])
    )
    db.refresh(explanation)
    assert explanation.status is AnalysisRunStatus.COMPLETED
    message = db.scalar(
        select(AnalysisMessage).where(
            AnalysisMessage.run_id == explanation.id, AnalysisMessage.role == "assistant"
        )
    )
    assert "系数范围" in message.content
    assert "因果" in message.content


def test_two_derived_tool_budget_is_checked_before_publication(source_context) -> None:
    db, run, data = prepare(source_context, "correlation")
    run.budget = {**run.budget, "max_tool_calls": 2}
    db.commit()
    run_analysis(db, run_id=run.id, gateway=FakeGateway([]), metric_executor=lambda *_: data)
    db.refresh(run)
    assert run.error_code == "agent.tool_budget_exhausted"
    assert not db.scalar(
        select(AnalysisArtifact.id).where(
            AnalysisArtifact.run_id == run.id,
            AnalysisArtifact.artifact_type == "correlation_result",
        )
    )
