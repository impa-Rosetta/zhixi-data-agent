"""Bounded analytics on complete verified tables; never executes generated code."""

from __future__ import annotations

import json
import math
import statistics
import uuid
from typing import Literal, NoReturn, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr, model_validator

MAX_ROWS = 20_000
MAX_COLUMNS = 50
MAX_INPUT_BYTES = 20 * 1024 * 1024


class AdvancedAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class CorrelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: uuid.UUID
    x_field: StrictStr = Field(min_length=1, max_length=200)
    y_field: StrictStr = Field(min_length=1, max_length=200)
    method: Literal["pearson", "spearman"] = "pearson"

    @model_validator(mode="after")
    def different_fields(self) -> Self:
        if self.x_field == self.y_field:
            raise ValueError("correlation requires two different fields")
        return self


class CorrelationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    version: Literal[1] = 1
    source_artifact_id: uuid.UUID
    method: Literal["pearson", "spearman"]
    x_field: str
    y_field: str
    coefficient: float = Field(ge=-1, le=1)
    total_count: int = Field(ge=3, le=MAX_ROWS)
    sample_count: int = Field(ge=3, le=MAX_ROWS)
    dropped_count: int = Field(ge=0, le=MAX_ROWS)
    warning: str = "相关性不代表因果关系；样本选择及业务粒度可能影响结果。"


class IQRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    artifact_id: uuid.UUID
    field: StrictStr = Field(min_length=1, max_length=200)
    multiplier: StrictFloat = Field(default=1.5, ge=1, le=3)


class AnomalyPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    row_index: int = Field(ge=0, lt=MAX_ROWS)
    value: float
    direction: Literal["below", "above"]


class IQRResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    version: Literal[1] = 1
    source_artifact_id: uuid.UUID
    method: Literal["iqr"] = "iqr"
    field: str
    multiplier: float = Field(ge=1, le=3)
    quantile_method: Literal["linear"] = "linear"
    total_count: int = Field(ge=8, le=MAX_ROWS)
    sample_count: int = Field(ge=8, le=MAX_ROWS)
    dropped_count: int = Field(ge=0, le=MAX_ROWS)
    q1: float
    q3: float
    lower_bound: float
    upper_bound: float
    anomalies: tuple[AnomalyPoint, ...] = Field(max_length=MAX_ROWS)
    warning: str = "统计异常是需要复核的线索，不等于已确认的质量缺陷。"


def _fail(code: str, message: str) -> NoReturn:
    raise AdvancedAnalysisError(code, message)


def _table(result: dict[str, object]) -> tuple[list[str], list[list[object]]]:
    columns, rows = result.get("columns"), result.get("rows")
    if (
        not isinstance(columns, list)
        or not columns
        or not all(isinstance(name, str) and 0 < len(name) <= 200 for name in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(rows, list)
    ):
        _fail("analysis.invalid_table", "数据表结构不完整，请重新查询后分析。")
    # Explicit narrowing also keeps this module understandable to strict type checking.
    assert isinstance(columns, list) and isinstance(rows, list)
    if len(rows) > MAX_ROWS or len(columns) > MAX_COLUMNS:
        _fail("analysis.data_limit", "数据超过分析上限，请缩小范围或选择明确的抽样方案。")
    if result.get("truncated", False) is not False:
        _fail("analysis.incomplete_data", "当前结果被截断，不能据此分析完整数据。")
    count = result.get("row_count", len(rows))
    if isinstance(count, bool) or not isinstance(count, int) or count != len(rows):
        _fail("analysis.incomplete_data", "结果行数与数据不一致，请重新获取完整数据。")
    if not all(isinstance(row, list) and len(row) == len(columns) for row in rows):
        _fail("analysis.invalid_table", "数据行与字段不一致，请重新查询后分析。")
    try:
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdvancedAnalysisError(
            "analysis.invalid_table", "数据包含不合法或非有限的值，请先清理数据。"
        ) from exc
    if size > MAX_INPUT_BYTES:
        _fail("analysis.data_limit", "数据体积超过分析上限，请缩小范围。")
    return columns, rows


def _index(columns: list[str], field: str) -> int:
    if field not in columns:
        _fail("analysis.field_not_found", "选择的字段不在当前结果中，请确认分析对象。")
    return columns.index(field)


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail("analysis.non_numeric_field", "所选字段包含非数值，请选择数值字段或先清理数据。")
    assert isinstance(value, (int, float, str))
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise AdvancedAnalysisError(
            "analysis.non_numeric_field", "所选字段包含不合法的数值，请先清理数据。"
        ) from exc
    if not math.isfinite(number):
        _fail("analysis.numeric_range", "所选字段包含非有限数值，请先清理数据。")
    return number


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for position in ordered[start:end]:
            ranks[position] = rank
        start = end
    return ranks


def _centered_scaled(values: list[float]) -> list[float]:
    if min(values) == max(values):
        _fail("analysis.constant_field", "所选字段没有变化，无法计算有意义的相关性。")
    scale = max(abs(value) for value in values)
    normalized = [value / scale for value in values]
    mean = statistics.fmean(normalized)
    centered = [value - mean for value in normalized]
    spread = max(abs(value) for value in centered)
    if spread == 0:
        _fail("analysis.numeric_range", "字段变化超出数值精度，无法可靠计算相关性。")
    return [value / spread for value in centered]


def correlate_verified_result(
    result: dict[str, object], request: CorrelationRequest
) -> CorrelationResult:
    columns, rows = _table(result)
    x_index, y_index = _index(columns, request.x_field), _index(columns, request.y_field)
    pairs = [
        (_numeric(row[x_index]), _numeric(row[y_index]))
        for row in rows
        if row[x_index] is not None and row[y_index] is not None
    ]
    if len(pairs) < 3:
        _fail("analysis.insufficient_samples", "至少需要 3 对有效数值，请扩大数据范围。")
    x_values, y_values = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
    if request.method == "spearman":
        x_values, y_values = _average_ranks(x_values), _average_ranks(y_values)
    x, y = _centered_scaled(x_values), _centered_scaled(y_values)
    numerator = math.fsum(a * b for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(math.fsum(a * a for a in x)) * math.sqrt(math.fsum(b * b for b in y))
    coefficient = max(-1.0, min(1.0, numerator / denominator))
    return CorrelationResult(
        source_artifact_id=request.artifact_id,
        method=request.method,
        x_field=request.x_field,
        y_field=request.y_field,
        coefficient=coefficient,
        total_count=len(rows),
        sample_count=len(pairs),
        dropped_count=len(rows) - len(pairs),
    )


def _quantile(ordered: list[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    weight = position - lower
    upper = min(lower + 1, len(ordered) - 1)
    return (1 - weight) * ordered[lower] + weight * ordered[upper]


def detect_iqr_anomalies(result: dict[str, object], request: IQRRequest) -> IQRResult:
    columns, rows = _table(result)
    index = _index(columns, request.field)
    values = [
        (position, _numeric(row[index]))
        for position, row in enumerate(rows)
        if row[index] is not None
    ]
    if len(values) < 8:
        _fail("analysis.insufficient_samples", "IQR 检测至少需要 8 个有效样本，请扩大数据范围。")
    ordered = sorted(value for _, value in values)
    q1, q3 = _quantile(ordered, 0.25), _quantile(ordered, 0.75)
    spread = q3 - q1
    if spread == 0:
        _fail("analysis.zero_iqr", "数据的四分位距为零，IQR 方法无法可靠区分异常。")
    lower, upper = q1 - request.multiplier * spread, q3 + request.multiplier * spread
    if not all(math.isfinite(value) for value in (q1, q3, lower, upper)):
        _fail("analysis.numeric_range", "数据范围过大，无法生成可靠的异常阈值。")
    return IQRResult(
        source_artifact_id=request.artifact_id,
        field=request.field,
        multiplier=request.multiplier,
        total_count=len(rows),
        sample_count=len(values),
        dropped_count=len(rows) - len(values),
        q1=q1,
        q3=q3,
        lower_bound=lower,
        upper_bound=upper,
        anomalies=tuple(
            AnomalyPoint(
                row_index=position, value=value, direction="below" if value < lower else "above"
            )
            for position, value in values
            if value < lower or value > upper
        ),
    )
