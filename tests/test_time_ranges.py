from datetime import UTC, datetime

import pytest

from packages.agent_core.time_ranges import date_bounds, resolve_time_range


def test_recent_three_months_resolves_to_stable_half_open_months() -> None:
    resolved = resolve_time_range(
        "最近三个月",
        reference=datetime(2026, 9, 18, 8, 30, tzinfo=UTC),
    )
    assert resolved is not None
    assert resolved.start == datetime(2026, 7, 1, tzinfo=UTC)
    assert resolved.end == datetime(2026, 10, 1, tzinfo=UTC)


def test_named_year_and_all_available_ranges() -> None:
    reference = datetime(2026, 9, 18, tzinfo=UTC)
    assert date_bounds("去年", reference=reference) == (
        datetime(2025, 1, 1, tzinfo=UTC).date(),
        datetime(2026, 1, 1, tzinfo=UTC).date(),
    )
    assert resolve_time_range("all_available", reference=reference) is None
    assert resolve_time_range("未来三个月", reference=reference) is None


@pytest.mark.parametrize("value", ["2026年7月", "2026年07月", "2026-07", " 2026-7 "])
def test_calendar_month_is_independent_of_reference(value: str) -> None:
    resolved = resolve_time_range(value, reference=datetime(2027, 2, 10, tzinfo=UTC))
    assert resolved is not None
    assert resolved.start == datetime(2026, 7, 1, tzinfo=UTC)
    assert resolved.end == datetime(2026, 8, 1, tzinfo=UTC)


def test_calendar_december_rolls_into_next_year() -> None:
    assert date_bounds("2026年12月", reference=datetime(2026, 9, 27, tzinfo=UTC)) == (
        datetime(2026, 12, 1, tzinfo=UTC).date(),
        datetime(2027, 1, 1, tzinfo=UTC).date(),
    )


@pytest.mark.parametrize("value", ["2026年0月", "2026-13", "0000-07", "9999-12"])
def test_invalid_calendar_month_never_becomes_unfiltered_query(value: str) -> None:
    with pytest.raises(ValueError, match="^query.invalid_time_range$"):
        resolve_time_range(value, reference=datetime(2026, 9, 27, tzinfo=UTC))
