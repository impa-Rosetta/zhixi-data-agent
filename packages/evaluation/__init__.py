"""Versioned, deterministic evaluation contracts and scoring."""

from packages.evaluation.answer_claims import AnswerClaimCheck, verify_answer_claims
from packages.evaluation.contracts import EvaluationCase, EvaluationSuite, ObservedOutcome
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
    "score_case",
    "summarize_suite",
    "verify_answer_claims",
]
