"""Execute registered advanced tools and persist their verified chart lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.advanced_analysis_sources import load_advanced_analysis_input
from apps.worker.analysis_runtime import _as_int, _check_budget, _complete_derived_step
from packages.agent_core.contracts import AnalysisPlan, Intent
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisStepRecord,
    AnalysisStepStatus,
)
from packages.analysis_engine import ChartSeries, ChartSpec
from packages.analysis_engine.tools import bind_advanced_analysis_tools
from packages.model_gateway import ModelGatewayError
from packages.toolkit import build_default_registry


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def derive_advanced_artifacts(
    db: Session,
    *,
    run: AnalysisRun,
    plan: AnalysisPlan,
    intent: Intent,
    result: dict[str, object],
    source_artifact: AnalysisArtifact,
    source_evidence: AnalysisEvidence,
) -> tuple[AnalysisArtifact, AnalysisArtifact]:
    _check_budget(run, tool=True)
    if run.tool_calls + 2 > _as_int(run.budget.get("max_tool_calls"), 12):
        raise ModelGatewayError("agent.tool_budget_exhausted")
    planned = next(step for step in plan.steps if step.id == "advanced_analysis")
    step = db.scalar(
        select(AnalysisStepRecord).where(
            AnalysisStepRecord.run_id == run.id,
            AnalysisStepRecord.workspace_id == run.workspace_id,
            AnalysisStepRecord.step_key == "advanced_analysis",
        )
    )
    if step is None:
        raise RuntimeError("agent.step_missing")
    step.status = AnalysisStepStatus.RUNNING
    step.started_at = datetime.now(UTC)
    registry = build_default_registry()
    bind_advanced_analysis_tools(
        registry,
        lambda artifact_id: load_advanced_analysis_input(
            db,
            workspace_id=run.workspace_id,
            actor_user_id=run.created_by_user_id,
            artifact_id=artifact_id,
            active_run_id=run.id,
        ),
    )
    arguments = {**planned.arguments, "artifact_id": str(source_artifact.id)}
    summary = registry.invoke(planned.tool, arguments)
    artifact = _complete_derived_step(
        db,
        run=run,
        plan=plan,
        step_key="advanced_analysis",
        source_artifact=source_artifact,
        source_evidence=source_evidence,
        artifact_type="correlation_result"
        if intent.task_type == "correlation"
        else "anomaly_result",
        summary=summary,
        evidence_type="advanced_analysis",
        validation_type="advanced_analysis",
    )
    if artifact is None:
        raise RuntimeError("agent.step_missing")
    raw_columns, raw_rows = result.get("columns"), result.get("rows")
    assert isinstance(raw_columns, list) and isinstance(raw_rows, list)
    rows: list[list[float | int | None]]
    chart_type: Literal["scatter", "line"]
    if intent.task_type == "correlation":
        x, y = str(summary["x_field"]), str(summary["y_field"])
        ix, iy = raw_columns.index(x), raw_columns.index(y)
        columns = [x, y]
        rows = [
            [float(row[ix]), float(row[iy])]
            for row in raw_rows
            if isinstance(row, list) and row[ix] is not None and row[iy] is not None
        ]
        category = x
        series = [ChartSeries(field=y, label=y)]
        chart_type = "scatter"
    else:
        index = raw_columns.index(str(summary["field"]))
        points = summary["anomalies"]
        assert isinstance(points, list)
        abnormal = {point["row_index"] for point in points if isinstance(point, dict)}
        columns = ["row_index", "value", "anomaly_value"]
        rows = [
            [
                i + 1,
                float(row[index]) if row[index] is not None else None,
                float(row[index]) if i in abnormal else None,
            ]
            for i, row in enumerate(raw_rows)
            if isinstance(row, list)
        ]
        category = "row_index"
        series = [
            ChartSeries(field="value", label=str(summary["field"])),
            ChartSeries(field="anomaly_value", label="异常点"),
        ]
        chart_type = "line"
    data_summary: dict[str, object] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
        "source_artifact_id": str(source_artifact.id),
        "analysis_artifact_id": str(artifact.id),
    }
    dataset = AnalysisArtifact(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_type="visualization_data",
        summary=data_summary,
        content_digest=_digest(data_summary),
    )
    db.add(dataset)
    db.flush()
    reference: dict[str, object] = {
        "source_artifact_id": str(source_artifact.id),
        "source_evidence_id": str(source_evidence.id),
        "analysis_artifact_id": str(artifact.id),
        "transform_version": "1.0.0",
        "source_content_digest": source_artifact.content_digest,
        "source_evidence_digest": source_evidence.evidence_digest,
        "data_digest": dataset.content_digest,
    }
    dataset_evidence = AnalysisEvidence(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_id=dataset.id,
        evidence_type="advanced_chart_data",
        reference=reference,
        evidence_digest=_digest(reference),
    )
    db.add(dataset_evidence)
    db.flush()
    chart = ChartSpec(
        chart_type=chart_type,
        source_artifact_id=dataset.id,
        evidence_id=dataset_evidence.id,
        title=intent.goal[:200],
        category_field=category,
        series=series,
        row_limit=min(200, len(rows)),
        truncated=len(rows) > 200,
    )
    chart_artifact = _complete_derived_step(
        db,
        run=run,
        plan=plan,
        step_key="compose_visualization",
        source_artifact=dataset,
        source_evidence=dataset_evidence,
        artifact_type="chart_spec",
        summary=chart.model_dump(mode="json"),
        evidence_type="chart_spec",
        validation_type="chart_contract",
    )
    if chart_artifact is None:
        raise RuntimeError("agent.step_missing")
    return artifact, chart_artifact
