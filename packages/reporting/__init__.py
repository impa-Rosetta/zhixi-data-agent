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
    "correlation_result": ("analysis", "相关性分析"),
    "anomaly_result": ("analysis", "统计异常检测"),
    "visualization_data": ("data", "图表计算数据"),
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
        template_version="1.1.0"
        if any(
            section.source.artifact_type in {"correlation_result", "anomaly_result"}
            for section in sections
        )
        else "1.0.0",
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


def _summary_html(section: ReportSection, spec: ReportSpecV1) -> str:
    if section.source.artifact_type in {"correlation_result", "anomaly_result"}:
        from packages.agent_core.presentation import advanced_analysis_presentation

        presentation = advanced_analysis_presentation(section.summary)
        return "<p>" + html.escape(presentation.content) + "</p>"
    if section.kind == "chart":
        from packages.reporting.charts import render_chart_svg

        return render_chart_svg(section, spec)
    columns = section.summary.get("columns")
    rows = section.summary.get("rows")
    if (
        section.kind == "data"
        and isinstance(columns, list)
        and columns
        and all(isinstance(column, str) for column in columns)
        and isinstance(rows, list)
        and all(isinstance(row, list) and len(row) == len(columns) for row in rows)
    ):
        headers = "".join(f'<th scope="col">{html.escape(str(c))}</th>' for c in columns)
        body = "".join(
            "<tr>"
            + "".join(
                "<td>" + html.escape("无数据" if cell is None else str(cell)) + "</td>"
                for cell in row
            )
            + "</tr>"
            for row in rows
        )
        table = f"<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>"
        if not rows:
            table += "<p>没有符合条件的数据。</p>"
        extra = {k: v for k, v in section.summary.items() if k not in {"columns", "rows"}}
        if extra:
            table += (
                "<pre>"
                + html.escape(json.dumps(extra, ensure_ascii=False, sort_keys=True, indent=2))
                + "</pre>"
            )
        return table
    return (
        "<pre>"
        + html.escape(json.dumps(section.summary, ensure_ascii=False, sort_keys=True, indent=2))
        + "</pre>"
    )


def render_html(spec: ReportSpecV1) -> str:
    head = (
        '<meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        "<style>"
        "@page{size:A4;margin:20mm 18mm;}"
        "body{font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;"
        "color:#17213a;line-height:1.65;font-size:11pt;}"
        "h1{font-size:24pt;color:#243fbd;border-bottom:2px solid #dfe5ff;padding-bottom:12px;}"
        "h2{font-size:15pt;margin-top:24px;color:#243fbd;}"
        "section{border:1px solid #dfe5ee;border-radius:8px;"
        "padding:14px;margin:14px 0;}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fb;padding:12px;}"
        "table{width:100%;border-collapse:collapse;table-layout:fixed;}"
        "thead{display:table-header-group;}tr{break-inside:avoid;}"
        "th,td{border:1px solid #dfe5ee;padding:8px;text-align:left;overflow-wrap:anywhere;}"
        "th{background:#eef2ff;}h2{break-after:avoid;}"
        ".evidence{font-size:9pt;color:#52617a;overflow-wrap:anywhere;}</style>"
        f"<title>{html.escape(spec.title)}</title>"
    )
    sections = []
    for section in spec.sections:
        payload = _summary_html(section, spec)
        sections.append(
            "<section>"
            f"<h2>{html.escape(section.title)}</h2>" + payload + '<p class="evidence">'
            f"证据定位：Turn {section.source.turn_id} / "
            f"Artifact {section.source.artifact_id}"
            "</p>"
            "</section>"
        )
    return (
        '<!doctype html><html lang="zh-CN"><head>'
        + head
        + "</head><body>"
        + f"<h1>{html.escape(spec.title)}</h1>"
        + f"<p>生成时间：{html.escape(spec.generated_at.isoformat())}</p>"
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
