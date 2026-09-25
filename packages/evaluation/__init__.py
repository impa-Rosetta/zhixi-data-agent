"""Versioned, deterministic evaluation contracts and scoring."""

from packages.evaluation.answer_claims import AnswerClaimCheck, verify_answer_claims
from packages.evaluation.contracts import EvaluationCase, EvaluationSuite, ObservedOutcome
from packages.evaluation.observation import observe_clarification_run, observe_completed_run
from packages.evaluation.scoring import CaseScore, score_case
from packages.evaluation.suite_io import load_suite
from packages.evaluation.summary import SuiteSummary, summarize_suite

__all__ = [
    "AnswerClaimCheck",
    "CaseScore",
    "EvaluationCase",
    "EvaluationSuite",
    "ObservedOutcome",
    "SuiteSummary",
    "load_suite",
    "observe_clarification_run",
    "observe_completed_run",
    "score_case",
    "summarize_suite",
    "verify_answer_claims",
]
