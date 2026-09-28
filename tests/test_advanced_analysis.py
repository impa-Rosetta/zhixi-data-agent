"""Deterministic advanced analytics; no LLM calls or user database access."""

import math
import uuid

import pytest
from pydantic import ValidationError

from packages.analysis_engine.advanced import (
    AdvancedAnalysisError,
    CorrelationRequest,
    IQRRequest,
    correlate_verified_result,
    detect_iqr_anomalies,
)


def table(rows: list[list[object]]) -> dict[str, object]:
    return {"columns": ["x", "y"], "rows": rows, "row_count": len(rows), "truncated": False}


def correlation(result: dict[str, object], method: str = "pearson"):
    request = CorrelationRequest.model_validate(
        {"artifact_id": str(uuid.uuid4()), "x_field": "x", "y_field": "y", "method": method}
    )
    return correlate_verified_result(result, request)


def anomalies(values: list[object], multiplier: float = 1.5):
    request = IQRRequest(artifact_id=uuid.uuid4(), field="y", multiplier=multiplier)
    return detect_iqr_anomalies(table([[i, value] for i, value in enumerate(values)]), request)


@pytest.mark.parametrize("method", ["pearson", "spearman"])
@pytest.mark.parametrize("direction", [1, -1])
def test_perfect_correlation_preserves_source_and_causal_warning(method, direction) -> None:
    result = correlation(table([[i, direction * (i + 10)] for i in range(5)]), method)
    assert result.coefficient == pytest.approx(direction)
    assert result.method == method
    assert result.sample_count == 5
    assert result.dropped_count == 0
    assert result.total_count == 5
    assert "因果" in result.warning
    assert result.source_artifact_id


def test_spearman_uses_average_ranks_for_ties() -> None:
    # x ranks: 1.5,1.5,3,4; y ranks: 1,2.5,2.5,4.
    result = correlation(table([[1, 1], [1, 2], [2, 2], [3, 3]]), "spearman")
    assert result.coefficient == pytest.approx(3.75 / 4.5)


def test_pairwise_null_removal_does_not_independently_zip_columns() -> None:
    result = correlation(table([[1, None], [None, 99], [2, 4], [3, 6], [4, 8]]))
    assert result.coefficient == pytest.approx(1)
    assert result.sample_count == 3
    assert result.dropped_count == 2


def test_numeric_database_strings_and_large_numbers_are_stable() -> None:
    assert correlation(table([["1", "2"], ["2", "4"], ["3", "6"]])).coefficient == 1
    result = correlation(table([[-1e308, 1e308], [0, 0], [1e308, -1e308]]))
    assert math.isfinite(result.coefficient)
    assert result.coefficient == pytest.approx(-1)


@pytest.mark.parametrize("rows", [[[1, 2], [2, 3]], [[1, 2], [1, 3], [1, 4]]])
def test_small_or_constant_correlation_refuses_result(rows) -> None:
    with pytest.raises(AdvancedAnalysisError) as error:
        correlation(table(rows))
    assert error.value.code in {"analysis.insufficient_samples", "analysis.constant_field"}


@pytest.mark.parametrize("value", [True, False, "oops", float("nan"), float("inf"), "inf"])
def test_invalid_selected_numeric_values_are_not_silently_dropped(value) -> None:
    with pytest.raises(AdvancedAnalysisError):
        correlation(table([[1, 2], [2, 3], [3, value], [4, 5]]))


@pytest.mark.parametrize(
    "updates",
    [
        {"truncated": True},
        {"truncated": "false"},
        {"row_count": 8},
        {"row_count": True},
        {"columns": ["x", "x"]},
        {"columns": ["x", 1]},
        {"rows": [[1, 2], [2], [3, 4]]},
        {"rows": [[1, 2, 3]]},
        {"rows": "not rows"},
    ],
)
def test_malformed_or_incomplete_table_is_rejected(updates) -> None:
    result = {**table([[1, 2], [2, 3], [3, 4]]), **updates}
    with pytest.raises(AdvancedAnalysisError):
        correlation(result)


def test_fields_must_exist_and_be_different() -> None:
    with pytest.raises(ValidationError):
        CorrelationRequest(artifact_id=uuid.uuid4(), x_field="x", y_field="x")
    request = CorrelationRequest(artifact_id=uuid.uuid4(), x_field="missing", y_field="y")
    with pytest.raises(AdvancedAnalysisError, match="analysis.field_not_found"):
        correlate_verified_result(table([[1, 2], [2, 3], [3, 4]]), request)


def test_requests_reject_unknown_execution_fields_and_invalid_parameters() -> None:
    with pytest.raises(ValidationError):
        CorrelationRequest.model_validate(
            {"artifact_id": str(uuid.uuid4()), "x_field": "x", "y_field": "y", "sql": "SELECT 1"}
        )
    for value in (0.9, 3.1, True, "1.5", float("inf")):
        with pytest.raises(ValidationError):
            IQRRequest.model_validate(
                {"artifact_id": str(uuid.uuid4()), "field": "y", "multiplier": value}
            )


def test_iqr_linear_quartiles_and_original_row_indices() -> None:
    result = anomalies([None, 1, 2, 3, 4, 5, 6, 7, 100])
    assert result.sample_count == 8
    assert result.dropped_count == 1
    assert result.q1 == 2.75
    assert result.q3 == 6.25
    assert result.lower_bound == -2.5
    assert result.upper_bound == 11.5
    assert [(point.row_index, point.value) for point in result.anomalies] == [(8, 100)]
    assert result.method == "iqr"
    assert "Isolation" not in result.model_dump_json()


def test_iqr_boundary_values_are_not_anomalies() -> None:
    assert anomalies(list(range(8))).anomalies == ()


@pytest.mark.parametrize("values", [[1] * 8, list(range(7)), [None] * 9])
def test_iqr_zero_spread_or_small_sample_is_explicit(values) -> None:
    with pytest.raises(AdvancedAnalysisError) as error:
        anomalies(values)
    assert error.value.code in {"analysis.zero_iqr", "analysis.insufficient_samples"}


def test_iqr_extreme_limits_cannot_publish_infinite_bounds() -> None:
    with pytest.raises(AdvancedAnalysisError, match="analysis.numeric_range"):
        anomalies([-1e308] * 4 + [1e308] * 4)


def test_resource_limits_fail_before_computation() -> None:
    with pytest.raises(AdvancedAnalysisError, match="analysis.data_limit"):
        correlation(table([[i, i] for i in range(20_001)]))
    with pytest.raises(AdvancedAnalysisError, match="analysis.data_limit"):
        correlation({"columns": [f"c{i}" for i in range(51)], "rows": [[1] * 51] * 3})
    with pytest.raises(AdvancedAnalysisError, match="analysis.data_limit"):
        correlation(table([[i, "a" * (8 * 1024 * 1024)] for i in range(3)]))
