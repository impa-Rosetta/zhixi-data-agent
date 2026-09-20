from __future__ import annotations

import hashlib
import html
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, cast

from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisValidation,
)
from packages.shared_contracts.reports import (
    ReportArtifactType,
    ReportSection,
    ReportSectionKind,
    ReportSourceRef,
    ReportSpecV1,
)

_ALLOWED_TYPES: Final[dict[str, tuple[ReportSectionKind, str]]] = {
    "query_result": ("data", "可信查询结果"),
    "analysis_summary": ("analysis", "统计分析摘要"),
    "chart_spec": ("chart", "可视化图表"),
}


class ReportCompositionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReportComposition:
    spec: ReportSpecV1
    source_digest: str


def compose_report_spec(
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    title: str,
    generated_at: datetime,
    runs: Sequence[AnalysisRun],
    turns: Sequence[AnalysisTurn],
    artifacts: Sequence[AnalysisArtifact],
    evidence: Sequence[AnalysisEvidence],
    validations: Sequence[AnalysisValidation],
) -> ReportComposition:
    normalized_title = " ".join(title.split())
    if not normalized_title:
        raise ReportCompositionError("report.title_required")
    if not artifacts:
        raise ReportCompositionError("report.sources_required")

    run_by_id = {run.id: run for run in runs}
    turn_by_run_id = {turn.analysis_run_id: turn for turn in turns if turn.analysis_run_id}
    passed_by_run: dict[uuid.UUID, list[AnalysisValidation]] = {}
    for validation in validations:
        if validation.workspace_id != workspace_id:
            raise ReportCompositionError("report.workspace_mismatch")
        if validation.outcome == "passed":
            passed_by_run.setdefault(validation.run_id, []).append(validation)

    evidence_by_artifact: dict[uuid.UUID, list[AnalysisEvidence]] = {}
    for item in evidence:
        if item.workspace_id != workspace_id:
            raise ReportCompositionError("report.workspace_mismatch")
        if item.artifact_id is not None:
            evidence_by_artifact.setdefault(item.artifact_id, []).append(item)

    sections: list[ReportSection] = []
    for artifact in sorted(artifacts, key=lambda item: (item.created_at, str(item.id))):
        if artifact.workspace_id != workspace_id:
            raise ReportCompositionError("report.workspace_mismatch")
        mapping = _ALLOWED_TYPES.get(artifact.artifact_type)
        if mapping is None:
            raise ReportCompositionError("report.artifact_not_allowed")
        run = run_by_id.get(artifact.run_id)
        if run is None or run.workspace_id != workspace_id:
            raise ReportCompositionError("report.run_not_found")
        if run.conversation_id != conversation_id:
            raise ReportCompositionError("report.conversation_mismatch")
        if run.status is not AnalysisRunStatus.COMPLETED:
            raise ReportCompositionError("report.run_not_completed")
        turn = turn_by_run_id.get(run.id)
        if turn is None or turn.workspace_id != workspace_id:
            raise ReportCompositionError("report.turn_not_found")
        artifact_evidence = evidence_by_artifact.get(artifact.id, [])
        if not artifact_evidence:
            raise ReportCompositionError("report.evidence_required")
        artifact_validations = passed_by_run.get(run.id, [])
        if not artifact_validations:
            raise ReportCompositionError("report.validation_required")
        canonical_summary = _canonical_json(artifact.summary)
        digest = hashlib.sha256(canonical_summary.encode("utf-8")).hexdigest()
        if digest != artifact.content_digest:
            raise ReportCompositionError("report.artifact_digest_mismatch")
        kind, section_title = mapping
        sections.append(
            ReportSection(
                kind=kind,
                title=section_title,
                summary=artifact.summary,
                source=ReportSourceRef(
                    turn_id=turn.id,
                    run_id=run.id,
                    artifact_id=artifact.id,
                    artifact_type=cast(ReportArtifactType, artifact.artifact_type),
                    content_digest=artifact.content_digest,
                    evidence_ids=sorted((item.id for item in artifact_evidence), key=str),
                    validation_ids=sorted(
                        (item.id for item in artifact_validations),
                        key=str,
                    ),
                ),
            )
        )

    spec = ReportSpecV1(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        created_by_user_id=created_by_user_id,
        generated_at=generated_at,
        title=normalized_title,
        sections=sections,
    )
    canonical = json.dumps(
        spec.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ReportComposition(
        spec=spec,
        source_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def render_markdown(spec: ReportSpecV1) -> str:
    lines = [
        f"# {spec.title}",
        "",
        f"- 生成时间：{spec.generated_at.isoformat()}",
        f"- 模板版本：{spec.template_version}",
        "",
    ]
    for section in spec.sections:
        lines.extend(
            [
                f"## {section.title}",
                "",
                json.dumps(section.summary, ensure_ascii=False, sort_keys=True, indent=2),
                "",
                (
                    f"证据定位：Turn {section.source.turn_id} / "
                    f"Artifact {section.source.artifact_id}"
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_html(spec: ReportSpecV1) -> str:
    sections = []
    for section in spec.sections:
        payload = html.escape(
            json.dumps(section.summary, ensure_ascii=False, sort_keys=True, indent=2)
        )
        sections.append(
            "<section>"
            f"<h2>{html.escape(section.title)}</h2>"
            f"<pre>{payload}</pre>"
            '<p class="evidence">'
            f"证据定位：Turn {section.source.turn_id} / "
            f"Artifact {section.source.artifact_id}"
            "</p>"
            "</section>"
        )
    return (
        '<!doctype html><html lang="zh-CN"><head>'
        '<meta charset="utf-8">'
        f"<title>{html.escape(spec.title)}</title>"
        "</head><body>"
        f"<h1>{html.escape(spec.title)}</h1>"
        f"<p>生成时间：{html.escape(spec.generated_at.isoformat())}</p>"
        + "".join(sections)
        + "</body></html>"
    )


def _canonical_json(value: dict[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ReportCompositionError("report.summary_not_serializable") from exc


__all__ = [
    "ReportComposition",
    "ReportCompositionError",
    "compose_report_spec",
    "render_html",
    "render_markdown",
]
