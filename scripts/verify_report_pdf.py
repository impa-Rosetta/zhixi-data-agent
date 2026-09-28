"""Offline renderer fixture; not a verified business report or storage acceptance."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from packages.reporting.generation import render_report
from packages.shared_contracts.reports import ReportSection, ReportSourceRef, ReportSpecV1


def main() -> None:
    fixture_id = UUID("00000000-0000-4000-8000-000000000001")
    source = ReportSourceRef(
        turn_id=fixture_id,
        run_id=fixture_id,
        artifact_id=fixture_id,
        artifact_type="query_result",
        content_digest="a" * 64,
        evidence_ids=[fixture_id],
        validation_ids=[fixture_id],
    )
    spec = ReportSpecV1(
        workspace_id=fixture_id,
        conversation_id=fixture_id,
        created_by_user_id=fixture_id,
        generated_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        title="中文表格与分页验收（模拟数据）",
        sections=[
            ReportSection(
                kind="data",
                title="模拟质量数据明细",
                summary={
                    "columns": ["样本序号", "生产月份", "不良率（百分比）"],
                    "rows": [[i, "2026年9月", 3.0] for i in range(1, 61)],
                    "说明": "仅用于中文与分页测试，证据编号为模拟编号，非正式业务报告。",
                },
                source=source,
            )
        ],
    )
    result = render_report(spec)
    for item in result.files:
        if item.extension == "pdf":
            output = Path("/output/chinese-table-pagination-verification.pdf")
            with output.open("xb") as handle:
                handle.write(item.content)
            print(f"PDF bytes={len(item.content)} sha256={item.sha256_digest}")


if __name__ == "__main__":
    main()
