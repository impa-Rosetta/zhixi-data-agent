from datetime import UTC, datetime

from apps.api.services.sampling import next_schedule_run
from packages.shared_contracts.data_sources import ScanScheduleUpdateRequest


def test_daily_schedule_advances_after_local_slot() -> None:
    payload = ScanScheduleUpdateRequest(
        version=0,
        enabled=True,
        frequency="daily",
        timezone="Asia/Shanghai",
        local_time="03:30:00",
    )
    result = next_schedule_run(payload, now=datetime(2026, 9, 5, 0, 0, tzinfo=UTC))
    assert result == datetime(2026, 9, 5, 19, 30, tzinfo=UTC)


def test_weekly_schedule_uses_python_weekday() -> None:
    payload = ScanScheduleUpdateRequest(
        version=0,
        enabled=True,
        frequency="weekly",
        timezone="UTC",
        local_time="12:00:00",
        day_of_week=0,
    )
    result = next_schedule_run(payload, now=datetime(2026, 9, 5, 10, 0, tzinfo=UTC))
    assert result == datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def test_nonexistent_dst_time_moves_to_next_valid_minute() -> None:
    payload = ScanScheduleUpdateRequest(
        version=0,
        enabled=True,
        frequency="daily",
        timezone="America/New_York",
        local_time="02:30:00",
    )
    result = next_schedule_run(payload, now=datetime(2026, 3, 8, 5, 0, tzinfo=UTC))
    assert result == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)


def test_disabled_schedule_has_no_next_run() -> None:
    payload = ScanScheduleUpdateRequest(
        version=0,
        enabled=False,
        frequency="daily",
        timezone="UTC",
        local_time="12:00:00",
    )
    assert next_schedule_run(payload) is None
