"""Recheck advanced report inputs and recompute immutable derived data before export."""

from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.api.services.advanced_analysis_sources import load_advanced_analysis_input
from packages.agent_core.persistence import AnalysisArtifact, AnalysisEvidence
from packages.analysis_engine import ChartSpec
from packages.analysis_engine.advanced import AdvancedAnalysisError
from packages.analysis_engine.tools import VerifiedAnalysisInput, bind_advanced_analysis_tools
from packages.reporting import ReportCompositionError
from packages.toolkit import ToolRegistryError, build_default_registry


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def verify_advanced_report_sources(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    artifacts: list[AnalysisArtifact],
    evidence: list[AnalysisEvidence],
) -> None:
    by_id = {str(item.id): item for item in artifacts}
    by_evidence = {str(item.id): item for item in evidence}
    advanced = [
        item for item in artifacts if item.artifact_type in {"correlation_result", "anomaly_result"}
    ]
    advanced_runs = {item.run_id for item in advanced}
    if any(
        item.artifact_type == "visualization_data" and item.run_id not in advanced_runs
        for item in artifacts
    ):
        raise ReportCompositionError("report.advanced_lineage_invalid")
    try:
        for item in advanced:
            summary = item.summary
            source_id = uuid.UUID(str(summary.get("source_artifact_id")))
            source = by_id.get(str(source_id))
            if source is None or source.run_id != item.run_id:
                raise ValueError("source missing")
            verified = load_advanced_analysis_input(
                db,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                artifact_id=source_id,
            )
            registry = build_default_registry()

            def load(
                artifact_id: uuid.UUID,
                source: VerifiedAnalysisInput = verified,
            ) -> VerifiedAnalysisInput:
                return source

            bind_advanced_analysis_tools(registry, load)
            correlation = item.artifact_type == "correlation_result"
            keys = ("x_field", "y_field", "method") if correlation else ("field", "multiplier")
            expected = registry.invoke(
                "analysis.correlate" if correlation else "analysis.detect_anomaly",
                {"artifact_id": str(source_id), **{key: summary[key] for key in keys}},
            )
            if expected != summary:
                raise ValueError("derived result mismatch")
            _verify_transform(item, source, str(verified.evidence_id), by_evidence)
            datasets = [
                data
                for data in artifacts
                if data.artifact_type == "visualization_data" and data.run_id == item.run_id
            ]
            if len(datasets) != 1:
                raise ValueError("dataset missing or ambiguous")
            dataset = datasets[0]
            raw_columns, raw_rows = verified.data["columns"], verified.data["rows"]
            assert isinstance(raw_columns, list) and isinstance(raw_rows, list)
            rows: list[list[float | int | None]]
            if correlation:
                x, y = str(summary["x_field"]), str(summary["y_field"])
                ix, iy = raw_columns.index(x), raw_columns.index(y)
                columns = [x, y]
                rows = [
                    [float(row[ix]), float(row[iy])]
                    for row in raw_rows
                    if isinstance(row, list) and row[ix] is not None and row[iy] is not None
                ]
                category, fields, chart_type = x, [y], "scatter"
            else:
                index = raw_columns.index(str(summary["field"]))
                anomalies = summary["anomalies"]
                assert isinstance(anomalies, list)
                abnormal = {point["row_index"] for point in anomalies if isinstance(point, dict)}
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
                category, fields, chart_type = "row_index", ["value", "anomaly_value"], "line"
            expected_data = {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": False,
                "source_artifact_id": str(source.id),
                "analysis_artifact_id": str(item.id),
            }
            if dataset.summary != expected_data or dataset.content_digest != _digest(expected_data):
                raise ValueError("chart data mismatch")
            data_evidence = [entry for entry in evidence if entry.artifact_id == dataset.id]
            if len(data_evidence) != 1:
                raise ValueError("chart data evidence missing")
            entry = data_evidence[0]
            expected_ref = {
                "source_artifact_id": str(source.id),
                "source_evidence_id": str(verified.evidence_id),
                "analysis_artifact_id": str(item.id),
                "transform_version": "1.0.0",
                "source_content_digest": source.content_digest,
                "source_evidence_digest": by_evidence[str(verified.evidence_id)].evidence_digest,
                "data_digest": dataset.content_digest,
            }
            if (
                entry.run_id != item.run_id
                or entry.reference != expected_ref
                or entry.evidence_digest != _digest(expected_ref)
            ):
                raise ValueError("chart data evidence mismatch")
            charts = [
                chart
                for chart in artifacts
                if chart.artifact_type == "chart_spec" and chart.run_id == item.run_id
            ]
            if len(charts) != 1:
                raise ValueError("chart missing or ambiguous")
            chart = charts[0]
            spec = ChartSpec.model_validate(chart.summary)
            if (
                spec.source_artifact_id != dataset.id
                or spec.evidence_id != entry.id
                or spec.chart_type != chart_type
                or spec.category_field != category
                or [series.field for series in spec.series] != fields
                or spec.row_limit != min(200, len(rows))
                or spec.truncated != (len(rows) > 200)
            ):
                raise ValueError("chart contract mismatch")
            _verify_transform(chart, dataset, str(entry.id), by_evidence)
    except (
        AdvancedAnalysisError,
        ToolRegistryError,
        ValidationError,
        ValueError,
        KeyError,
        TypeError,
        AssertionError,
        OverflowError,
    ) as exc:
        raise ReportCompositionError("report.advanced_lineage_invalid") from exc


def _verify_transform(
    artifact: AnalysisArtifact,
    source: AnalysisArtifact,
    source_evidence_id: str,
    evidence: dict[str, AnalysisEvidence],
) -> None:
    matches = [entry for entry in evidence.values() if entry.artifact_id == artifact.id]
    parent = evidence[source_evidence_id]
    expected_ref = {
        "source_artifact_id": str(source.id),
        "source_evidence_id": source_evidence_id,
        "transform_version": "1.0.0",
    }
    digest = hashlib.sha256(
        f"{parent.evidence_digest}:{artifact.content_digest}".encode()
    ).hexdigest()
    if (
        len(matches) != 1
        or matches[0].run_id != artifact.run_id
        or matches[0].reference != expected_ref
        or matches[0].evidence_digest != digest
    ):
        raise ValueError("transform evidence mismatch")
