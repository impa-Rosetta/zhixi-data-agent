import hashlib
import json
import uuid

import pytest
from sqlalchemy import select
from test_advanced_agent_runtime import prepare
from test_advanced_analysis_sources import source_context as source_context

from apps.api.services.analysis_reports import (
    AnalysisReportServiceError,
    create_report,
    read_report_file,
)
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisReport,
    AnalysisReportFormat,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.model_gateway import FakeGateway
from packages.platform_core.models import DataSourceStatus
from packages.reporting import render_html, render_markdown
from packages.reporting.charts import render_chart_svg
from packages.reporting.generation import claim_report, publish_report, render_report
from packages.shared_contracts.reports import CreateAnalysisReportRequest


def report_context(context, task):
    db, run, data = prepare(context, task)
    user, workspace = context[1:3]
    conversation = AnalysisConversation(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="advanced-report",
        title="高级分析",
        status=AnalysisConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.flush()
    turn = AnalysisTurn(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        sequence=1,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.COMPLETED,
        analysis_run_id=run.id,
    )
    db.add(turn)
    db.flush()
    run.conversation_id, run.turn_id = conversation.id, turn.id
    db.commit()
    run_analysis(db, run_id=run.id, gateway=FakeGateway([]), metric_executor=lambda *_: data)
    payload = CreateAnalysisReportRequest(
        conversation_id=conversation.id,
        turn_ids=[turn.id],
        title="高级分析报告",
    )
    return db, user, workspace, run, payload


def create(context):
    db, user, workspace, _, payload = context
    return create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report",
        payload=payload,
    )


@pytest.mark.parametrize(
    "task,kind", [("correlation", "correlation_result"), ("anomaly_detection", "anomaly_result")]
)
def test_report_contains_actual_advanced_result_and_visible_numeric_svg(source_context, task, kind):
    context = report_context(source_context, task)
    report = create(context)
    assert kind in {section.source.artifact_type for section in report.spec.sections}
    assert "visualization_data" in {
        section.source.artifact_type for section in report.spec.sections
    }
    document = render_html(report.spec)
    assert "<svg" in document and "<circle" in document
    assert "相关性不代表因果" in document if task == "correlation" else "统计异常" in document
    assert "证据定位" in render_markdown(report.spec)
    assert "NaN" not in document and "Infinity" not in document


@pytest.mark.parametrize("change", ["source_disabled", "result", "dataset", "chart_source"])
def test_report_rejects_invalid_advanced_lineage_before_publishing(source_context, change):
    context = report_context(source_context, "correlation")
    db, _, _, run, _ = context
    if change == "source_disabled":
        source_context[3]["source"].status = DataSourceStatus.DISABLED
    else:
        kind = {
            "result": "correlation_result",
            "dataset": "visualization_data",
            "chart_source": "chart_spec",
        }[change]
        artifact = db.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == run.id, AnalysisArtifact.artifact_type == kind
            )
        )
        if change == "result":
            artifact.summary = {**artifact.summary, "coefficient": -0.5}
        elif change == "dataset":
            artifact.summary = {**artifact.summary, "rows": [[0, 999]]}
        else:
            artifact.summary = {**artifact.summary, "source_artifact_id": str(uuid.uuid4())}
        artifact.content_digest = hashlib.sha256(
            json.dumps(
                artifact.summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    db.commit()
    with pytest.raises(AnalysisReportServiceError):
        create(context)
    assert db.scalar(select(AnalysisReport.id)) is None


@pytest.mark.parametrize(
    "change",
    ["membership", "result_evidence", "dataset_evidence", "chart_evidence", "chart_method"],
)
def test_advanced_report_rechecks_permission_and_every_derived_evidence(source_context, change):
    from packages.agent_core.persistence import AnalysisEvidence

    context = report_context(source_context, "correlation")
    db, _, _, run, _ = context
    if change == "membership":
        db.delete(source_context[3]["member"])
    elif change == "chart_method":
        chart = db.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == run.id, AnalysisArtifact.artifact_type == "chart_spec"
            )
        )
        chart.summary = {**chart.summary, "chart_type": "line"}
    else:
        kind = {
            "result_evidence": "correlation_result",
            "dataset_evidence": "visualization_data",
            "chart_evidence": "chart_spec",
        }[change]
        artifact = db.scalar(
            select(AnalysisArtifact).where(
                AnalysisArtifact.run_id == run.id, AnalysisArtifact.artifact_type == kind
            )
        )
        entry = db.scalar(
            select(AnalysisEvidence).where(AnalysisEvidence.artifact_id == artifact.id)
        )
        entry.evidence_digest = "0" * 64
    db.commit()
    with pytest.raises(AnalysisReportServiceError):
        create(context)
    assert db.scalar(select(AnalysisReport.id)) is None


@pytest.mark.parametrize(
    "change",
    [
        "nonfinite",
        "bool",
        "bad_row",
        "incomplete",
        "nulls",
        "constant",
        "extreme",
        "xss",
        "truncated",
    ],
)
def test_static_report_chart_is_bounded_escaped_and_never_invents_zeroes(source_context, change):
    report = create(report_context(source_context, "correlation"))
    chart = next(section for section in report.spec.sections if section.kind == "chart")
    data = next(
        section
        for section in report.spec.sections
        if section.source.artifact_type == "visualization_data"
    )
    if change == "nonfinite":
        data.summary["rows"][0][1] = float("inf")
    elif change == "bool":
        data.summary["rows"][0][1] = True
    elif change == "bad_row":
        data.summary["rows"][0] = [0]
    elif change == "incomplete":
        data.summary["row_count"] = 999
    elif change == "nulls":
        data.summary["rows"] = [[None, None] for _ in range(10)]
    elif change == "constant":
        data.summary["rows"] = [[1, 1] for _ in range(10)]
    elif change == "extreme":
        data.summary["rows"] = [[-1e308, -1e308], [1e308, 1e308]]
        data.summary["row_count"] = 2
    elif change == "xss":
        chart.summary["title"] = '<script>alert("x")</script>'
    else:
        chart.summary["row_limit"] = 3
        chart.summary["truncated"] = True
    result = render_chart_svg(chart, report.spec)
    if change in {"nonfinite", "bool", "bad_row", "incomplete"}:
        assert "<svg" not in result and "保留原始参数" in result
    elif change == "nulls":
        assert "没有可绘制" in result
    else:
        assert "<circle" in result and "NaN" not in result and "Infinity" not in result
    if change == "xss":
        assert "<script>" not in result and "&lt;script&gt;" in result
    if change == "truncated":
        assert result.count("<circle") == 3 and "仅展示前3行" in result


@pytest.mark.parametrize("task", ["correlation", "anomaly_detection"])
def test_advanced_report_generation_publication_and_verified_download(source_context, task):
    context = report_context(source_context, task)
    db, user, workspace, _, _ = context
    report = create(context)
    db.commit()
    claim = claim_report(db, report.id)
    assert claim is not None
    seen = []

    def pdf_renderer(document):
        assert "<svg" in document and "<circle" in document
        seen.append(document)
        return b"%PDF-1.7 offline fixture"

    class Storage:
        def __init__(self):
            self.objects = {}

        def put(self, key, content, media_type):
            self.objects[key] = content

        def delete(self, key):
            self.objects.pop(key, None)

        def get(self, key, *, max_bytes):
            assert len(self.objects[key]) <= max_bytes
            return self.objects[key]

    generated = render_report(claim.spec, pdf_renderer=pdf_renderer)
    storage = Storage()
    publish_report(
        db,
        report_id=report.id,
        generated=generated,
        storage=storage,
        expected_attempt_count=claim.attempt_count,
    )
    assert len(storage.objects) == 3 and len(seen) == 1
    for file in generated.files:
        content, _, _ = read_report_file(
            db,
            workspace_id=workspace.id,
            report_id=report.id,
            format_value=AnalysisReportFormat(file.format),
            storage=storage,
            actor_user_id=user.id,
        )
        assert hashlib.sha256(content).hexdigest() == file.sha256_digest
        if file.format is AnalysisReportFormat.HTML:
            assert b"<svg" in content
