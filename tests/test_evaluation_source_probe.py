from packages.query_engine.security import validate_sql
from scripts.verify_evaluation_source import EXPECTED, SQL, verify_rows


def test_fixed_source_probe_uses_existing_sql_gate_and_exact_values() -> None:
    report = validate_sql(SQL, dialect="postgres", allowed_relations={"public.quality_inspections"})
    assert report.dependencies == ("public.quality_inspections",)
    assert verify_rows(EXPECTED, truncated=False)


def test_probe_rejects_wrong_missing_extra_and_truncated_results() -> None:
    assert not verify_rows(EXPECTED, truncated=True)
    assert not verify_rows(EXPECTED[:2], truncated=False)
    assert not verify_rows((*EXPECTED, EXPECTED[0]), truncated=False)
    assert not verify_rows((EXPECTED[0], EXPECTED[0], EXPECTED[2]), truncated=False)
    assert not verify_rows((("2026-07", 8, 400, "2.00"), *EXPECTED[1:]), truncated=False)
    assert not verify_rows((("2026-07", None, 400, "1.75"), *EXPECTED[1:]), truncated=False)
