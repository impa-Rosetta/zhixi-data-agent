"""Coverage and pass-rate aggregation without hiding unexecuted cases."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from packages.evaluation.contracts import EvaluationSuite
from packages.evaluation.scoring import CaseScore


@dataclass(frozen=True)
class SuiteSummary:
    total: int
    passed: int
    failed: int
    infra_error: int
    blocked: int
    not_run: int
    evaluated_pass_rate: Decimal | None
    coverage_rate: Decimal
    all_case_pass_rate: Decimal


def summarize_suite(
    suite: EvaluationSuite,
    scores: tuple[CaseScore, ...],
    *,
    blocked_case_ids: frozenset[str] = frozenset(),
) -> SuiteSummary:
    case_ids = {case.id for case in suite.cases}
    scored_ids = [score.case_id for score in scores]
    if len(scored_ids) != len(set(scored_ids)):
        raise ValueError("duplicate case scores")
    if not set(scored_ids).issubset(case_ids) or not blocked_case_ids.issubset(case_ids):
        raise ValueError("unknown case ID in summary")
    if set(scored_ids) & blocked_case_ids:
        raise ValueError("case cannot be both scored and blocked")
    passed = sum(score.status == "passed" for score in scores)
    failed = sum(score.status == "failed" for score in scores)
    infra_error = sum(score.status == "infra_error" for score in scores)
    blocked = len(blocked_case_ids)
    total = len(case_ids)
    evaluated = passed + failed
    return SuiteSummary(
        total=total,
        passed=passed,
        failed=failed,
        infra_error=infra_error,
        blocked=blocked,
        not_run=total - len(scores) - blocked,
        evaluated_pass_rate=Decimal(passed) / Decimal(evaluated) if evaluated else None,
        coverage_rate=Decimal(evaluated) / Decimal(total),
        all_case_pass_rate=Decimal(passed) / Decimal(total),
    )
