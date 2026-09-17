import uuid

from packages.analysis_engine import compose_chart_spec, describe_verified_result


def test_descriptive_statistics_only_use_numeric_verified_columns() -> None:
    artifact_id = uuid.uuid4()
    summary = describe_verified_result(
        {
            "columns": ["month", "defect_rate", "note"],
            "rows": [
                ["2026-01", 2.0, "ok"],
                ["2026-02", 4.0, "masked"],
                ["2026-03", None, "ok"],
            ],
        },
        source_artifact_id=artifact_id,
    )

    assert summary is not None
    assert summary.source_artifact_id == artifact_id
    assert len(summary.numeric_columns) == 1
    column = summary.numeric_columns[0]
    assert column.field == "defect_rate"
    assert column.count == 2
    assert column.null_count == 1
    assert column.mean == 3.0
    assert column.standard_deviation == 1.0


def test_chart_spec_references_source_and_never_contains_executable_options() -> None:
    artifact_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    spec = compose_chart_spec(
        {
            "columns": ["inspection_month", "defect_rate"],
            "rows": [["2026-01", 2.0], ["2026-02", 3.0]],
            "truncated": False,
        },
        source_artifact_id=artifact_id,
        evidence_id=evidence_id,
        title="月度不良率趋势",
    )

    assert spec is not None
    assert spec.chart_type == "line"
    assert spec.category_field == "inspection_month"
    assert spec.series[0].field == "defect_rate"
    payload = spec.model_dump(mode="json")
    assert payload["source_artifact_id"] == str(artifact_id)
    assert "option" not in payload
    assert "javascript" not in str(payload).lower()


def test_scalar_results_do_not_create_misleading_statistics_or_charts() -> None:
    artifact_id = uuid.uuid4()
    result = {"columns": ["defect_rate"], "rows": [[2.4]]}
    assert describe_verified_result(result, source_artifact_id=artifact_id) is None
    assert compose_chart_spec(
        result,
        source_artifact_id=artifact_id,
        evidence_id=None,
        title="不良率",
    ) is None
