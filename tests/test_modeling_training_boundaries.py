from dataclasses import replace

import pytest

from packages.modeling.data import ModelDataError
from packages.modeling.training import train_model
from tests.test_modeling_training import prepared


def test_identical_timestamps_cannot_fake_future_holdout():
    data = prepared(split="time", time_field="observed_at", intended_use="future_prediction")
    column = data.columns.index("observed_at")
    rows = tuple(
        tuple("2026-01-01T00:00:00+00:00" if j == column else value for j, value in enumerate(row))
        for row in data.rows
    )
    with pytest.raises(ModelDataError, match="insufficient_split"):
        train_model(replace(data, rows=rows))


def test_naive_timestamp_rejected():
    data = prepared(split="time", time_field="observed_at")
    column = data.columns.index("observed_at")
    rows = tuple(
        tuple("2026-01-01T00:00:00" if j == column else value for j, value in enumerate(row))
        for row in data.rows
    )
    with pytest.raises(ModelDataError, match="timezone"):
        train_model(replace(data, rows=rows))


def test_temporal_split_missing_class_is_not_success():
    data = prepared("logistic_regression", "classification", split="time", time_field="observed_at")
    column = data.columns.index("quality_label")
    # Replace only target, preserving time values and feature types.
    rows = tuple(
        tuple(
            ("class-a" if i < 800 else "class-b") if j == column else value
            for j, value in enumerate(row)
        )
        for i, row in enumerate(data.rows)
    )
    with pytest.raises(ModelDataError, match="split_missing_class"):
        train_model(replace(data, rows=rows))


def test_constant_validation_target_reports_undefined_r2():
    data = prepared()
    column = data.columns.index("defect_rate")
    rows = tuple(
        tuple(2.0 if j == column else value for j, value in enumerate(row)) for row in data.rows
    )
    output = train_model(replace(data, rows=rows))
    for metrics in (output.result.metrics, output.result.baseline_metrics):
        r2 = next(metric for metric in metrics if metric.name == "r2")
        assert r2.value is None and r2.unavailable_reason == "constant_validation_target"


def test_single_group_cannot_fake_independent_holdout():
    data = prepared(split="group", group_field="device")
    column = data.columns.index("device")
    rows = tuple(
        tuple("device-1" if j == column else value for j, value in enumerate(row))
        for row in data.rows
    )
    with pytest.raises(ModelDataError, match="invalid_split"):
        train_model(replace(data, rows=rows))
