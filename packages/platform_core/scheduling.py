from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from packages.platform_core.models import ScheduleFrequency


class ScheduleExpressionError(ValueError):
    pass


def _valid_local_candidate(local_day: date, *, local_time: time, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    naive = datetime.combine(local_day, local_time)
    candidate = naive.replace(tzinfo=zone, fold=0)
    round_trip = candidate.astimezone(UTC).astimezone(zone)
    if round_trip.replace(tzinfo=None) == naive:
        return candidate
    for minutes in range(1, 181):
        shifted = naive + timedelta(minutes=minutes)
        candidate = shifted.replace(tzinfo=zone, fold=0)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == shifted:
            return candidate
    raise ScheduleExpressionError("No valid local execution time could be resolved")


def calculate_next_run(
    *,
    enabled: bool,
    frequency: ScheduleFrequency,
    timezone: str,
    local_time: time,
    day_of_week: int | None,
    now: datetime | None = None,
) -> datetime | None:
    if not enabled:
        return None
    current = (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    local_day = current.date()
    if frequency is ScheduleFrequency.WEEKLY:
        if day_of_week is None:
            raise ScheduleExpressionError("Weekly schedules require day_of_week")
        local_day += timedelta(days=(day_of_week - local_day.weekday()) % 7)
    candidate = _valid_local_candidate(local_day, local_time=local_time, timezone=timezone)
    if candidate <= current:
        interval = 1 if frequency is ScheduleFrequency.DAILY else 7
        candidate = _valid_local_candidate(
            local_day + timedelta(days=interval), local_time=local_time, timezone=timezone
        )
    return candidate.astimezone(UTC)
