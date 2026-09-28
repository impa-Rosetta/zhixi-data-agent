"""Offline real PDF renderer smoke; synthetic references, not business/API acceptance."""

from datetime import UTC, datetime
from uuid import UUID

from packages.analysis_engine import ChartSeries, ChartSpec
from packages.analysis_engine.advanced import (
    CorrelationRequest,
    IQRRequest,
    correlate_verified_result,
    detect_iqr_anomalies,
)
from packages.reporting.generation import render_report
from packages.shared_contracts.reports import (
    ReportArtifactType,
    ReportSection,
    ReportSourceRef,
    ReportSpecV1,
)


def source(number: int, kind: ReportArtifactType) -> ReportSourceRef:
    return ReportSourceRef(
        turn_id=UUID(int=1),
        run_id=UUID(int=2),
        artifact_id=UUID(int=number),
        artifact_type=kind,
        content_digest="a" * 64,
        evidence_ids=[UUID(int=3)],
        validation_ids=[UUID(int=4)],
    )


def main() -> None:
    rows = [[i, 2 * i if i < 11 else 100] for i in range(12)]
    data: dict[str, object] = {
        "columns": ["x", "y"],
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
    }
    correlation = correlate_verified_result(
        data,
        CorrelationRequest(artifact_id=UUID(int=5), x_field="x", y_field="y"),
    ).model_dump(mode="json")
    anomaly = detect_iqr_anomalies(
        data,
        IQRRequest(artifact_id=UUID(int=5), field="y"),
    ).model_dump(mode="json")
    cases = [
        (
            "correlation_result",
            correlation,
            "scatter",
            ["x", "y"],
            rows,
            "x",
            [ChartSeries(field="y", label="不良量")],
        ),
        (
            "anomaly_result",
            anomaly,
            "line",
            ["row_index", "value", "anomaly_value"],
            [[i + 1, row[1], row[1] if i == 11 else None] for i, row in enumerate(rows)],
            "row_index",
            [
                ChartSeries(field="value", label="不良量"),
                ChartSeries(field="anomaly_value", label="异常点"),
            ],
        ),
    ]
    for kind, summary, chart_type, columns, chart_rows, category, series in cases:
        assert isinstance(chart_rows, list)
        # Explicit literals keep the fixture contracts strict and easy to audit.
        artifact_type: ReportArtifactType = (
            "correlation_result" if kind == "correlation_result" else "anomaly_result"
        )
        chart = ChartSpec(
            chart_type="scatter" if chart_type == "scatter" else "line",
            source_artifact_id=UUID(int=7),
            title="高级分析图表（模拟数据）",
            category_field=category,
            series=series,
        )
        spec = ReportSpecV1(
            workspace_id=UUID(int=1),
            conversation_id=UUID(int=2),
            created_by_user_id=UUID(int=3),
            generated_at=datetime.now(UTC),
            template_version="1.1.0",
            title="高级分析报告渲染检查（模拟数据）",
            sections=[
                ReportSection(
                    kind="analysis",
                    title="计算结果",
                    summary=summary,
                    source=source(6, artifact_type),
                ),
                ReportSection(
                    kind="data",
                    title="图表数据",
                    summary={
                        "columns": columns,
                        "rows": chart_rows,
                        "row_count": len(chart_rows),
                        "truncated": False,
                    },
                    source=source(7, "visualization_data"),
                ),
                ReportSection(
                    kind="chart",
                    title="图表",
                    summary=chart.model_dump(mode="json"),
                    source=source(8, "chart_spec"),
                ),
            ],
        )
        generated = render_report(spec)
        html_file = next(file for file in generated.files if file.extension == "html")
        pdf_file = next(file for file in generated.files if file.extension == "pdf")
        assert b"<svg" in html_file.content and html_file.content.count(b"<circle") >= 12
        if kind == "anomaly_result":
            assert b'fill="#dc4c64"' in html_file.content
        assert pdf_file.content.startswith(b"%PDF-") and len(pdf_file.content) > 1000
        print(f"{kind}: real PDF bytes={len(pdf_file.content)} sha256={pdf_file.sha256_digest}")


if __name__ == "__main__":
    main()
