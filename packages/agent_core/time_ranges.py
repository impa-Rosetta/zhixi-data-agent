"""Deterministic parsing for the bounded relative time phrases accepted by the Agent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class ResolvedTimeRange:
    start: datetime
    end: datetime


_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十二": 12,
}


def resolve_time_range(value: str | None, *, reference: datetime) -> ResolvedTimeRange | None:
    if value is None or value in {"all_available", "全部", "所有时间"}:
        return None
    normalized = value.strip().casefold()
    reference = reference.astimezone(UTC)
    month_start = datetime(reference.year, reference.month, 1, tzinfo=UTC)
    if normalized in {"本月", "this_month"}:
        return ResolvedTimeRange(month_start, _shift_months(month_start, 1))
    if normalized in {"上月", "last_month"}:
        start = _shift_months(month_start, -1)
        return ResolvedTimeRange(start, month_start)
    if normalized in {"今年", "this_year"}:
        start = datetime(reference.year, 1, 1, tzinfo=UTC)
        return ResolvedTimeRange(start, datetime(reference.year + 1, 1, 1, tzinfo=UTC))
    if normalized in {"去年", "last_year"}:
        start = datetime(reference.year - 1, 1, 1, tzinfo=UTC)
        return ResolvedTimeRange(start, datetime(reference.year, 1, 1, tzinfo=UTC))
    if normalized in {"最近一年", "近一年", "last_12_months"}:
        return ResolvedTimeRange(_shift_months(month_start, -11), _shift_months(month_start, 1))
    match = re.search(r"(?:最近|近)([0-9一二两三四五六七八九十]{1,2})个?月", normalized)
    if match:
        count = _number(match.group(1))
        if 1 <= count <= 24:
            return ResolvedTimeRange(
                _shift_months(month_start, -(count - 1)),
                _shift_months(month_start, 1),
            )
    return None


def date_bounds(value: str | None, *, reference: datetime) -> tuple[date, date] | None:
    resolved = resolve_time_range(value, reference=reference)
    return None if resolved is None else (resolved.start.date(), resolved.end.date())


def _number(value: str) -> int:
    if value.isdigit():
        return int(value)
    return _CHINESE_NUMBERS.get(value, 0)


def _shift_months(value: datetime, offset: int) -> datetime:
    index = value.year * 12 + value.month - 1 + offset
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


__all__ = ["ResolvedTimeRange", "date_bounds", "resolve_time_range"]
