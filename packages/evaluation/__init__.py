"""Versioned, deterministic evaluation contracts and scoring."""

from packages.evaluation.agent_behavior import (
    AgentBehaviorTrace,
    capture_agent_behavior_trace,
    observe_agent_behavior,
)
from packages.evaluation.answer_claims import AnswerClaimCheck, verify_answer_claims
from packages.evaluation.contracts import EvaluationCase, EvaluationSuite, ObservedOutcome
from packages.evaluation.observation import observe_clarification_run, observe_completed_run
from packages.evaluation.runner import OfflineBatchResult, OfflineCaseExecution, run_offline_suite
from packages.evaluation.scoring import CaseScore, score_case
from packages.evaluation.suite_io import load_suite
from packages.evaluation.summary import SuiteSummary, summarize_suite

__all__ = [
    "AgentBehaviorTrace",
    "AnswerClaimCheck",
    "CaseScore",
    "EvaluationCase",
    "EvaluationSuite",
    "ObservedOutcome",
    "OfflineBatchResult",
    "OfflineCaseExecution",
    "SuiteSummary",
    "load_suite",
    "capture_agent_behavior_trace",
    "observe_agent_behavior",
    "observe_clarification_run",
    "observe_completed_run",
    "score_case",
    "run_offline_suite",
    "summarize_suite",
    "verify_answer_claims",
]
