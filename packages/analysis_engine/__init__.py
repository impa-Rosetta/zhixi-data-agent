"""Deterministic analytics and constrained visualization contracts."""

from __future__ import annotations

import math
import statistics
import uuid
from typing import Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, Field


class DescriptiveColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float = Field(ge=0)


class DescriptiveSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    source_artifact_id: uuid.UUID
    row_count: int = Field(ge=0, le=1_000_000)
    numeric_columns: list[DescriptiveColumn] = Field(max_length=50)


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    chart_type: Literal["line", "bar", "horizontal_bar", "scatter"]
    source_artifact_id: uuid.UUID
    evidence_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    category_field: str = Field(min_length=1, max_length=200)
    series: list[ChartSeries] = Field(min_length=1, max_length=10)
    row_limit: int = Field(default=200, ge=1, le=200)
    truncated: bool = False


def describe_verified_result(
    result: dict[str, object],
    *,
    source_artifact_id: uuid.UUID,
) -> DescriptiveSummary | None:
    columns, rows = _table(result)
    if len(rows) < 2:
        return None
    summaries: list[DescriptiveColumn] = []
    for index, name in enumerate(columns):
        values: list[float] = []
        null_count = 0
        for row in rows:
            value = row[index] if index < len(row) else None
            if value is None:
                null_count += 1
            elif _is_number(value):
                values.append(float(value))
        if not values:
            continue
        summaries.append(
            DescriptiveColumn(
                field=name,
                count=len(values),
                null_count=null_count,
                minimum=min(values),
                maximum=max(values),
                mean=statistics.fmean(values),
                median=statistics.median(values),
                standard_deviation=statistics.pstdev(values),
            )
        )
    if not summaries:
        return None
    return DescriptiveSummary(
        source_artifact_id=source_artifact_id,
        row_count=len(rows),
        numeric_columns=summaries,
    )


def compose_chart_spec(
    result: dict[str, object],
    *,
    source_artifact_id: uuid.UUID,
    evidence_id: uuid.UUID | None,
    title: str,
) -> ChartSpec | None:
    columns, rows = _table(result)
    if len(columns) < 2 or len(rows) < 2:
        return None
    numeric = [
        name
        for index, name in enumerate(columns)
        if any(index < len(row) and _is_number(row[index]) for row in rows)
    ]
    if not numeric:
        return None
    category = next((name for name in columns if name not in numeric), columns[0])
    series = [ChartSeries(field=name, label=name) for name in numeric if name != category][:10]
    if not series:
        return None
    normalized = category.casefold()
    temporal = any(
        marker in normalized
        for marker in (
            "time",
            "date",
            "day",
            "week",
            "month",
            "quarter",
            "year",
            "日期",
            "时间",
            "月",
            "周",
            "年",
        )
    )
    chart_type: Literal["line", "bar", "horizontal_bar", "scatter"] = (
        "line" if temporal else "horizontal_bar" if len(rows) > 8 else "bar"
    )
    return ChartSpec(
        chart_type=chart_type,
        source_artifact_id=source_artifact_id,
        evidence_id=evidence_id,
        title=title[:200] or "分析结果",
        category_field=category,
        series=series,
        row_limit=min(200, len(rows)),
        truncated=bool(result.get("truncated", False)) or len(rows) > 200,
    )


def _table(result: dict[str, object]) -> tuple[list[str], list[list[object]]]:
    raw_columns = result.get("columns")
    raw_rows = result.get("rows")
    columns = (
        [item for item in raw_columns if isinstance(item, str)]
        if isinstance(raw_columns, list)
        else []
    )
    rows = (
        [list(item) for item in raw_rows if isinstance(item, list)]
        if isinstance(raw_rows, list)
        else []
    )
    return columns, rows


def _is_number(value: object) -> TypeGuard[int | float | str]:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    return False


__all__ = [
    "ChartSeries",
    "ChartSpec",
    "DescriptiveColumn",
    "DescriptiveSummary",
    "compose_chart_spec",
    "describe_verified_result",
]
