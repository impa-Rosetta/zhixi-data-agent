"""Deterministic synthetic observations; never writes or modifies business data."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta


def manufacturing_training_fixture(count: int = 1000, seed: int = 42) -> dict[str, object]:
    if type(count) is not int or not 1000 <= count <= 20_000:
        raise ValueError("model.synthetic_count_limit")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("model.synthetic_seed_invalid")
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[list[object]] = []
    for i in range(count):
        line = i % 4
        downtime = round(rng.uniform(0, 120), 2)
        temperature = round(rng.uniform(18, 40), 2)
        inspection = rng.randint(500, 1200)
        injected = i % 97 == 0
        rate = max(0.002, 0.005 + downtime * 0.00015 + line * 0.001 + rng.uniform(-0.003, 0.003))
        if injected:
            rate += 0.08
        defects = round(inspection * rate)
        rows.append(
            [
                (start + timedelta(hours=i)).isoformat(),
                f"line-{line + 1}",
                f"device-{i % 16 + 1}",
                downtime,
                temperature,
                inspection + rng.randint(0, 50),
                inspection,
                defects,
                round(defects / inspection, 6),
                "high" if rate > 0.018 else "normal",
                int(injected),
            ]
        )
    return {
        "columns": [
            "observed_at",
            "line",
            "device",
            "downtime_minutes",
            "temperature",
            "production_qty",
            "inspection_qty",
            "defect_qty",
            "defect_rate",
            "quality_label",
            "injected_anomaly",
        ],
        "rows": rows,
        "row_count": count,
        "truncated": False,
        "simulation": {
            "version": 1,
            "seed": seed,
            "synthetic": True,
            "warning": "模拟生成关系不代表企业实证；目标与其派生字段不可同时作为特征。",
            "rule": "rate=max(0.002,0.005+downtime*0.00015+line*0.001+noise); every 97th row +0.08",
        },
    }
