import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
    AnalysisValidation,
)
from packages.reporting import (
    ReportCompositionError,
    compose_report_spec,
    render_html,
    render_markdown,
)
from packages.shared_contracts.reports import CreateAnalysisReportRequest


def _source(*, summary: dict[str, object] | None = None) -> dict[str, Any]:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    run_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    artifact_summary = summary or {"columns": ["月份", "不良率"], "rows": [["9月", 3.0]]}
    artifact_digest = hashlib.sha256(
        json.dumps(
            artifact_summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    run = AnalysisRun(
        id=run_id,
        workspace_id=workspace_id,
        created_by_user_id=uuid.uuid4(),
        conversation_id=conversation_id,
        turn_id=turn_id,
        idempotency_key="run-1",
        status=AnalysisRunStatus.COMPLETED,
        created_at=now,
    )
    turn = AnalysisTurn(
        id=turn_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        sequence=1,
        analysis_run_id=run_id,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.COMPLETED,
        created_at=now,
    )
    artifact = AnalysisArtifact(
        id=artifact_id,
        workspace_id=workspace_id,
        run_id=run_id,
        artifact_type="query_result",
        summary=artifact_summary,
        content_digest=artifact_digest,
        created_at=now,
    )
    evidence = AnalysisEvidence(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        run_id=run_id,
        artifact_id=artifact_id,
        evidence_type="query_execution",
        reference={"trust": "trusted"},
        evidence_digest="b" * 64,
        created_at=now,
    )
    validation = AnalysisValidation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        run_id=run_id,
        validation_type="evidence",
        outcome="passed",
        findings=[],
        created_at=now,
    )
    return {
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "created_by_user_id": run.created_by_user_id,
        "title": "  第三季度   质量分析报告 ",
        "generated_at": now,
        "runs": [run],
        "turns": [turn],
        "artifacts": [artifact],
        "evidence": [evidence],
        "validations": [validation],
    }


def test_composition_is_deterministic_and_normalizes_title() -> None:
    source = _source()
    first = compose_report_spec(**source)
    second = compose_report_spec(**source)

    assert first.source_digest == second.source_digest
    assert first.spec.title == "第三季度 质量分析报告"
    assert first.spec.sections[0].source.evidence_ids


def test_composition_rejects_missing_evidence() -> None:
    source = _source()
    source["evidence"] = []

    with pytest.raises(ReportCompositionError) as error:
        compose_report_spec(**source)

    assert error.value.code == "report.evidence_required"


def test_composition_rejects_unpassed_validation() -> None:
    source = _source()
    source["validations"][0].outcome = "failed"

    with pytest.raises(ReportCompositionError) as error:
        compose_report_spec(**source)

    assert error.value.code == "report.validation_required"


def test_composition_rejects_cross_workspace_artifact() -> None:
    source = _source()
    source["artifacts"][0].workspace_id = uuid.uuid4()

    with pytest.raises(ReportCompositionError) as error:
        compose_report_spec(**source)

    assert error.value.code == "report.workspace_mismatch"


def test_composition_rejects_tampered_artifact_digest() -> None:
    source = _source()
    source["artifacts"][0].content_digest = "a" * 64

    with pytest.raises(ReportCompositionError) as error:
        compose_report_spec(**source)

    assert error.value.code == "report.artifact_digest_mismatch"


def test_html_escapes_untrusted_text_and_markdown_keeps_evidence() -> None:
    source = _source(summary={"note": "<script>alert('x')</script>"})
    composition = compose_report_spec(**source)

    html = render_html(composition.spec)
    markdown = render_markdown(composition.spec)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert '<meta http-equiv="Content-Security-Policy"' in html
    assert "default-src &#39;none&#39;" in html
    assert "<style>" in html
    assert "Noto Sans CJK SC" in html
    assert "证据定位" in markdown
    assert str(composition.spec.sections[0].source.artifact_id) in markdown


def test_create_report_request_rejects_duplicate_turns() -> None:
    turn_id = uuid.uuid4()

    with pytest.raises(ValidationError):
        CreateAnalysisReportRequest(
            conversation_id=uuid.uuid4(),
            turn_ids=[turn_id, turn_id],
            title="质量报告",
        )


def test_create_report_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreateAnalysisReportRequest.model_validate(
            {
                "conversation_id": str(uuid.uuid4()),
                "turn_ids": [str(uuid.uuid4())],
                "title": "质量报告",
                "unexpected": True,
            }
        )
