"""Static, escaped SVG charts for frozen advanced report datasets; no scripts or URLs."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Callable

from pydantic import ValidationError

from packages.analysis_engine import ChartSpec
from packages.shared_contracts.reports import ReportSection, ReportSpecV1


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("invalid chart number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite chart number")
    return result


def _axis(values: list[float], start: float, end: float) -> Callable[[float], float]:
    scale = max((abs(value) for value in values), default=1.0) or 1.0
    low, high = min(values) / scale, max(values) / scale
    if low == high:
        low, high = low - 0.5, high + 0.5
    return lambda value: start + ((value / scale - low) / (high - low)) * (end - start)


def render_chart_svg(section: ReportSection, report: ReportSpecV1) -> str:
    fallback = (
        "<pre>"
        + html.escape(json.dumps(section.summary, ensure_ascii=False, sort_keys=True, indent=2))
        + "</pre>"
    )
    try:
        spec = ChartSpec.model_validate(section.summary)
        sources = [
            item
            for item in report.sections
            if item.source.artifact_id == spec.source_artifact_id
            and item.source.artifact_type == "visualization_data"
        ]
        if not sources:
            return fallback  # Preserve existing report charts without changing their contract.
        if len(sources) != 1 or spec.chart_type not in {"scatter", "line"}:
            raise ValueError("invalid report chart")
        data = sources[0].summary
        columns, raw_rows = data["columns"], data["rows"]
        if not isinstance(columns, list) or not isinstance(raw_rows, list):
            raise ValueError("invalid chart dataset")
        if data.get("row_count") != len(raw_rows) or data.get("truncated") is not False:
            raise ValueError("incomplete chart dataset")
        ix = columns.index(spec.category_field)
        indices = [columns.index(series.field) for series in spec.series]
        rows = raw_rows[: spec.row_limit]
        pairs: list[list[tuple[float, float] | None]] = []
        for index in indices:
            points: list[tuple[float, float] | None] = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(columns):
                    raise ValueError("invalid row")
                points.append(
                    None
                    if row[ix] is None or row[index] is None
                    else (_number(row[ix]), _number(row[index]))
                )
            pairs.append(points)
        valid = [point for series in pairs for point in series if point is not None]
        if not valid:
            return "<p>当前数据没有可绘制的有效数值。</p>"
        xs, ys = [point[0] for point in valid], [point[1] for point in valid]
        x, y = _axis(xs, 80, 620), _axis(ys, 285, 45)
        title = html.escape(spec.title)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 350" '
            f'role="img" aria-label="{title}" style="width:100%;height:auto">',
            f"<title>{title}</title>",
            '<path d="M80 45 V285 H620" fill="none" stroke="#8793ad"/>',
        ]
        for value in sorted(set([min(ys), max(ys)])):
            parts.append(
                f'<text x="72" y="{y(value):.3f}" text-anchor="end" '
                f'font-size="12">{value:.6g}</text>'
            )
        for value in sorted(set([min(xs), max(xs)])):
            parts.append(
                f'<text x="{x(value):.3f}" y="308" text-anchor="middle" '
                f'font-size="12">{value:.6g}</text>'
            )
        for series, points in zip(spec.series, pairs, strict=True):
            color = "#dc4c64" if series.field == "anomaly_value" else "#4554e8"
            segment: list[str] = []
            for point in [*points, None]:
                if point is None:
                    if spec.chart_type == "line" and len(segment) > 1:
                        parts.append(
                            f'<polyline points="{" ".join(segment)}" fill="none" '
                            f'stroke="{color}" stroke-width="2"/>'
                        )
                    segment = []
                    continue
                px, py = x(point[0]), y(point[1])
                segment.append(f"{px:.3f},{py:.3f}")
                parts.append(f'<circle cx="{px:.3f}" cy="{py:.3f}" r="4" fill="{color}"/>')
        labels = " / ".join(series.label for series in spec.series)
        parts.append(
            f'<text x="350" y="337" text-anchor="middle" font-size="12">'
            f"{html.escape(spec.category_field)} · {html.escape(labels)}</text></svg>"
        )
        if spec.truncated or len(raw_rows) > spec.row_limit:
            parts.append(f"<p>图表仅展示前{spec.row_limit}行，完整数据见图表计算数据章节。</p>")
        return "".join(parts)
    except (ValidationError, ValueError, TypeError, KeyError, OverflowError):
        # Never draw invented zeroes for incompatible data; retained payload is auditable.
        return "<p>图表数据不符合绘制要求，保留原始参数供核查。</p>" + fallback
