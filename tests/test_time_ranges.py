from datetime import UTC, datetime

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
