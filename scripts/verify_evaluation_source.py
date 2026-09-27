"""Verify the dedicated synthetic source through product SQL gates and read-only execution."""

from __future__ import annotations

import json
from decimal import Decimal

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import NetworkPolicyRules
from packages.query_engine.runtime import execute_read_only
from packages.query_engine.security import validate_sql

SQL = """SELECT to_char(date_trunc('month', inspected_at), 'YYYY-MM') AS month,
SUM(defect_quantity) AS defects, SUM(inspected_quantity) AS inspected,
ROUND(100.0 * SUM(defect_quantity) / SUM(inspected_quantity), 2) AS defect_rate
FROM public.quality_inspections
WHERE inspected_at >= '2026-07-01' AND inspected_at < '2026-10-01'
GROUP BY 1 ORDER BY 1"""
EXPECTED = (
    ("2026-07", 7, 400, Decimal("1.75")),
    ("2026-08", 11, 400, Decimal("2.75")),
    ("2026-09", 12, 400, Decimal("3.00")),
)


def verify_rows(rows: tuple[tuple[object, ...], ...], *, truncated: bool) -> bool:
    if truncated or len(rows) != len(EXPECTED):
        return False
    for row, expected in zip(rows, EXPECTED, strict=True):
        if len(row) != 4 or row[0] != expected[0]:
            return False
        try:
            if any(
                Decimal(str(value)) != Decimal(str(target))
                for value, target in zip(row[1:], expected[1:], strict=True)
            ):
                return False
        except (ValueError, ArithmeticError):
            return False
    return True


def main() -> int:
    report = validate_sql(SQL, dialect="postgres", allowed_relations={"public.quality_inspections"})
    try:
        result = execute_read_only(
            DataSourceType.POSTGRESQL,
            ConnectionTarget("source-evaluation", 5432, "factory_demo", TlsMode.DISABLE),
            # Public, synthetic fixture credentials; never production or provider credentials.
            ConnectorCredentials("zhixi_reader", "reader-local-only"),
            NetworkPolicyRules.from_strings(
                allowed_private_cidrs=["172.16.0.0/12"],
                allowed_ports=[5432],
            ),
            SQL,
            (),
            row_limit=3,
        )
    except ConnectorError:
        print(json.dumps({"status": "infra_error", "code": "evaluation.source_unavailable"}))
        return 1
    valid = verify_rows(result.rows, truncated=result.truncated)
    print(
        json.dumps(
            {
                "status": "passed" if valid else "failed",
                "scope": "real-postgresql-source-precondition-not-agent-golden-score",
                "sql_gate_digest": report.digest,
                "row_count": len(result.rows),
                "rows": result.rows,
                "truncated": result.truncated,
                "production_network_policy_unchanged": True,
            },
            default=str,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
