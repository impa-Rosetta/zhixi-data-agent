"""Serial offline orchestration; adapters own isolated product fixtures, never scoring."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from packages.evaluation.contracts import EvaluationCase, EvaluationSuite, ObservedOutcome
from packages.evaluation.scoring import CaseScore, score_case
from packages.evaluation.summary import SuiteSummary, summarize_suite

ExecutionErrorCode = Literal[
    "evaluation.precondition_failed",
    "evaluation.execution_failed",
    "evaluation.fixture_unavailable",
    "evaluation.cleanup_failed",
    "evaluation.suite_changed",
    "evaluation.case_isolation_failed",
]


class OfflineExecutionError(Exception):
    def __init__(self, code: ExecutionErrorCode, *, blocked: bool = False) -> None:
        if code not in {
            "evaluation.precondition_failed",
            "evaluation.execution_failed",
            "evaluation.fixture_unavailable",
            "evaluation.cleanup_failed",
            "evaluation.suite_changed",
            "evaluation.case_isolation_failed",
        } or (blocked and code != "evaluation.precondition_failed"):
            raise ValueError("invalid offline error contract")
        super().__init__(code)
        self.code = code
        self.blocked = blocked


@dataclass(frozen=True)
class OfflineCaseExecution:
    observation: ObservedOutcome
    run_ids: tuple[uuid.UUID, ...] = ()


class OfflineCaseSession(Protocol):
    def execute(self) -> OfflineCaseExecution: ...


OfflineCaseFactory = Callable[[EvaluationCase], AbstractContextManager[OfflineCaseSession]]


@dataclass(frozen=True)
class OfflineBatchResult:
    run_id: uuid.UUID
    suite_version: str
    suite_digest: str
    synthetic_dataset_id: str
    semantic_version: str
    scores: tuple[CaseScore, ...]
    blocked_case_ids: frozenset[str]
    run_references: dict[str, tuple[uuid.UUID, ...]]
    summary: SuiteSummary
    category_summaries: dict[str, SuiteSummary]
    safety_summaries: dict[str, SuiteSummary]
    safety_failure_ids: tuple[str, ...]
    stopped_reason: ExecutionErrorCode | None

    def to_json(self) -> str:
        """Do not export prompts, raw observations, SQL or exception messages."""
        return json.dumps(
            {
                "track": "offline",
                "run_id": str(self.run_id),
                "suite_version": self.suite_version,
                "suite_digest": self.suite_digest,
                "synthetic_dataset_id": self.synthetic_dataset_id,
                "semantic_version": self.semantic_version,
                "scores": [asdict(score) for score in self.scores],
                "blocked_case_ids": sorted(self.blocked_case_ids),
                "run_references": {
                    key: [str(value) for value in values]
                    for key, values in self.run_references.items()
                },
                "summary": asdict(self.summary),
                "category_summaries": {
                    key: asdict(value) for key, value in self.category_summaries.items()
                },
                "safety_summaries": {
                    key: asdict(value) for key, value in self.safety_summaries.items()
                },
                "safety_failure_ids": self.safety_failure_ids,
                "stopped_reason": self.stopped_reason,
            },
            default=str,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def run_offline_suite(
    suite: EvaluationSuite,
    factory: OfflineCaseFactory,
    *,
    case_ids: frozenset[str] | None = None,
) -> OfflineBatchResult:
    """Use only reviewed offline adapters with synthetic isolated data and frozen gateways.

    This orchestrator does not authorize model calls or make arbitrary adapters network-safe.
    Each context must clean up all its own resources; cleanup uncertainty stops the batch.
    """
    # Re-validate and detach nested mutable expectation dictionaries before executing.
    frozen = EvaluationSuite.model_validate(suite.model_dump(mode="json"))
    digest = frozen.content_digest
    known_ids = {case.id for case in frozen.cases}
    if case_ids is not None and not case_ids.issubset(known_ids):
        raise ValueError("unknown case IDs")
    scores: list[CaseScore] = []
    blocked: set[str] = set()
    references: dict[str, tuple[uuid.UUID, ...]] = {}
    used_run_ids: set[uuid.UUID] = set()
    stopped: ExecutionErrorCode | None = None
    for case in frozen.cases:
        if case_ids is not None and case.id not in case_ids:
            continue
        stage = "prepare"
        result: OfflineCaseExecution | None = None
        failure: OfflineExecutionError | None = None
        try:
            # Pass a detached copy so an adapter cannot silently rewrite the expected result.
            with factory(EvaluationCase.model_validate(case.model_dump(mode="json"))) as session:
                stage = "execute"
                try:
                    result = session.execute()
                    if (
                        not isinstance(result, OfflineCaseExecution)
                        or not all(isinstance(value, uuid.UUID) for value in result.run_ids)
                        or not isinstance(result.observation, ObservedOutcome)
                    ):
                        raise TypeError("invalid offline adapter result")
                except OfflineExecutionError as exc:
                    failure = exc
                except Exception:
                    failure = OfflineExecutionError("evaluation.execution_failed")
                stage = "cleanup"
        except Exception:
            code: ExecutionErrorCode = (
                "evaluation.cleanup_failed"
                if stage == "cleanup"
                else "evaluation.fixture_unavailable"
            )
            scores.append(CaseScore(case.id, "infra_error", (), code))
            stopped = code
            break
        if frozen.content_digest != digest:
            scores.append(CaseScore(case.id, "infra_error", (), "evaluation.suite_changed"))
            stopped = "evaluation.suite_changed"
            break
        if failure is not None:
            if failure.blocked:
                blocked.add(case.id)
            else:
                scores.append(CaseScore(case.id, "infra_error", (), failure.code))
        elif result is not None:
            if used_run_ids.intersection(result.run_ids):
                scores.append(
                    CaseScore(case.id, "infra_error", (), "evaluation.case_isolation_failed")
                )
                stopped = "evaluation.case_isolation_failed"
                break
            used_run_ids.update(result.run_ids)
            if result.observation.infra_error_code is not None:
                scores.append(CaseScore(case.id, "infra_error", (), "evaluation.execution_failed"))
            else:
                scores.append(score_case(case, result.observation))
            references[case.id] = result.run_ids
        else:
            scores.append(CaseScore(case.id, "infra_error", (), "evaluation.execution_failed"))
    scored = tuple(scores)
    blocked_ids = frozenset(blocked)

    def group_summary(cases: tuple[EvaluationCase, ...]) -> SuiteSummary:
        ids = {item.id for item in cases}
        group = frozen.model_copy(update={"cases": cases})
        return summarize_suite(
            group,
            tuple(score for score in scored if score.case_id in ids),
            blocked_case_ids=blocked_ids & ids,
        )

    categories = {case.category for case in frozen.cases}
    probes = {case.probe_kind for case in frozen.cases if case.probe_kind is not None}
    security_ids = {case.id for case in frozen.cases if case.category == "security"}
    return OfflineBatchResult(
        run_id=uuid.uuid4(),
        suite_version=frozen.suite_version,
        suite_digest=digest,
        synthetic_dataset_id=frozen.synthetic_dataset_id,
        semantic_version=frozen.semantic_version,
        scores=scored,
        blocked_case_ids=blocked_ids,
        run_references=references,
        summary=summarize_suite(frozen, scored, blocked_case_ids=blocked_ids),
        category_summaries={
            category: group_summary(
                tuple(case for case in frozen.cases if case.category == category)
            )
            for category in sorted(categories)
        },
        safety_summaries={
            probe: group_summary(tuple(case for case in frozen.cases if case.probe_kind == probe))
            for probe in sorted(probes)
        },
        safety_failure_ids=tuple(
            score.case_id
            for score in scored
            if score.case_id in security_ids and score.status == "failed"
        ),
        stopped_reason=stopped,
    )
