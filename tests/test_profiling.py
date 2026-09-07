from datetime import date, datetime
from decimal import Decimal

import pytest

from packages.connectors.profiling import SampledColumn, SampledRelation, SamplingBudget
from packages.platform_core import profiling
from packages.platform_core.profiling import (
    build_profile_document,
    detect_sensitivity,
    mask_text,
)


def column(
    name: str,
    values: tuple[object | None, ...],
    data_type: str = "text",
    native_type: str = "varchar",
) -> SampledColumn:
    return SampledColumn(name, data_type, native_type, values)


def relation(*columns: SampledColumn, name: str = "orders") -> SampledRelation:
    return SampledRelation("public", name, 1_000, columns)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("customer_email", "email"),
        ("手机号", "phone"),
        ("id_card", "national_id"),
        ("bank_card_no", "bank_card"),
        ("password_hash", "password"),
        ("api_key", "secret_token"),
    ],
)
def test_sensitive_names_fail_closed(name: str, expected: str) -> None:
    match = detect_sensitivity(column(name, ("ordinary",)))
    assert match.sensitivity_type == expected
    assert match.confidence >= 0.98
    assert match.sample_allowed is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("person@example.com", "email"),
        ("13800138000", "phone"),
        ("11010519491231002X", "national_id"),
        ("4111111111111111", "bank_card"),
        ("sk-test-placeholder", "secret_token"),
        ("eyJhbGciOiJIUzI1NiJ9.payload.signature", "secret_token"),
    ],
)
def test_sensitive_values_are_detected(value: str, expected: str) -> None:
    match = detect_sensitivity(column("value", (value,)))
    assert match.sensitivity_type == expected
    assert match.sample_allowed is False


def test_invalid_identity_and_repeated_card_are_not_sensitive() -> None:
    assert detect_sensitivity(column("value", ("110105194912310021",))).sample_allowed
    assert detect_sensitivity(column("value", ("1111111111111111",))).sample_allowed


@pytest.mark.parametrize(
    ("data_type", "native_type"),
    [("binary", "bytea"), ("json", "jsonb"), ("text", "longblob"), ("geospatial", "geometry")],
)
def test_unsupported_types_never_allow_samples(data_type: str, native_type: str) -> None:
    match = detect_sensitivity(column("payload", (b"secret",), data_type, native_type))
    assert match.sensitivity_type == "unsupported_type"
    assert match.sample_allowed is False


def test_mask_text_redacts_embedded_values() -> None:
    original = (
        "contact person@example.com or 13800138000; card 4111111111111111; "
        "token sk-test-placeholder"
    )
    masked = mask_text(original)
    assert masked == "contact [EMAIL] or [PHONE]; card [NUMBER]; token [TOKEN]"
    assert "example.com" not in masked
    assert "13800138000" not in masked


def test_profile_builds_sampled_statistics_and_explicit_sources() -> None:
    document = build_profile_document(
        (
            relation(
                column("amount", (Decimal("10.5"), None, Decimal("20.0")), "number", "numeric"),
                column("ordered_on", (date(2026, 1, 2), date(2026, 1, 1)), "date", "date"),
                column("status", ("new", "done", "new", None)),
            ),
        ),
        SamplingBudget(),
    )
    amount, ordered_on, status = document.relations[0].columns
    assert amount.sample_row_count == 3
    assert amount.non_null_count == 2
    assert amount.sample_null_rate == pytest.approx(1 / 3)
    assert amount.sampled_distinct_count == 2
    assert amount.minimum_value == "10.5"
    assert amount.maximum_value == "20.0"
    assert ordered_on.minimum_value == "2026-01-01"
    assert ordered_on.maximum_value == "2026-01-02"
    assert status.minimum_length == 3
    assert status.maximum_length == 4
    assert status.average_length == pytest.approx(10 / 3)
    assert status.metric_sources["sample_null_rate"] == "sampled"
    assert status.metric_sources["estimated_row_count"] == "estimated"


def test_sensitive_profile_keeps_aggregates_but_no_values_or_ranges() -> None:
    raw = "person@example.com"
    document = build_profile_document(
        (relation(column("contact", (raw, None, raw))),), SamplingBudget()
    )
    result = document.relations[0].columns[0]
    assert result.sensitivity_type == "email"
    assert result.sample_null_rate == pytest.approx(1 / 3)
    assert result.sampled_distinct_count == 1
    assert result.samples == ()
    assert result.minimum_value is None
    assert result.maximum_value is None
    assert raw not in repr(document)


def test_rows_values_and_characters_are_bounded_defensively() -> None:
    values = tuple(f"value-{index}-" + "x" * 100 for index in range(30))
    document = build_profile_document(
        (relation(column("label", values)),),
        SamplingBudget(max_rows_per_table=7, max_values_per_column=3, max_value_chars=16),
    )
    result = document.relations[0].columns[0]
    assert result.sample_row_count == 7
    assert len(result.samples) == 3
    assert all(len(item.masked_value) <= 16 for item in result.samples)


def test_unicode_truncation_never_splits_utf8_and_obeys_table_budget() -> None:
    values = tuple(("数" * 220) + str(index) for index in range(4))
    document = build_profile_document(
        (relation(column("description", values)),),
        SamplingBudget(max_bytes_per_table=1_024, max_bytes_per_job=1_024),
    )
    result = document.relations[0]
    assert result.sample_bytes <= 1_024
    assert sum(item.byte_count for item in result.columns[0].samples) == result.sample_bytes
    assert all(
        item.masked_value.encode("utf-8").decode("utf-8") for item in result.columns[0].samples
    )
    assert document.budget_exhausted is True


def test_job_budget_is_shared_across_relations() -> None:
    values = tuple(("a" * 250) + str(index) for index in range(20))
    document = build_profile_document(
        (
            relation(column("description", values), name="first"),
            relation(column("description", values), name="second"),
        ),
        SamplingBudget(max_bytes_per_table=1_024, max_bytes_per_job=1_024),
    )
    assert document.sample_bytes <= 1_024
    assert document.relations[1].sample_bytes == 0
    assert document.budget_exhausted is True


def test_duplicate_and_nonfinite_values_are_not_persisted_twice() -> None:
    document = build_profile_document(
        (relation(column("score", (1.0, 1.0, float("nan"), float("inf")), "number", "float")),),
        SamplingBudget(),
    )
    samples = document.relations[0].columns[0].samples
    assert [(item.masked_value, item.value_type) for item in samples] == [("1.0", "number")]


def test_negative_row_estimate_is_treated_as_unknown() -> None:
    sampled = SampledRelation("public", "orders", -1, (column("id", (1,), "number", "int"),))
    result = build_profile_document((sampled,), SamplingBudget())
    assert result.relations[0].estimated_row_count is None
    assert result.relations[0].columns[0].estimated_row_count is None


def test_detector_failure_discards_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: SampledColumn) -> profiling.SensitivityMatch:
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(profiling, "detect_sensitivity", fail)
    raw = "must-not-survive"
    document = build_profile_document((relation(column("description", (raw,))),), SamplingBudget())
    result = document.relations[0].columns[0]
    assert result.sensitivity_type == "unknown_sensitive"
    assert result.sensitivity_reasons == ("detector:error",)
    assert result.samples == ()
    assert raw not in repr(document)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_rows_per_table": 0},
        {"max_values_per_column": 21},
        {"max_value_chars": 15},
        {"max_bytes_per_table": 1_023},
        {"max_bytes_per_table": 2_048, "max_bytes_per_job": 1_024},
    ],
)
def test_sampling_budget_rejects_invalid_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        SamplingBudget(**kwargs)


def test_supported_scalars_have_stable_value_types() -> None:
    document = build_profile_document(
        (
            relation(
                column("flag", (True,), "boolean", "bool"),
                column("created_at", (datetime(2026, 1, 1, 12, 0),), "datetime", "timestamp"),
                column("count", (2,), "number", "int"),
            ),
        ),
        SamplingBudget(),
    )
    assert [item.samples[0].value_type for item in document.relations[0].columns] == [
        "boolean",
        "datetime",
        "number",
    ]
