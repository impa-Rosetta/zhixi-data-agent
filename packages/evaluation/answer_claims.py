"""Verify displayed numeric answer claims against a single run's persisted evidence."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from packages.shared_contracts.agents import AnalysisRunViewResponse

ClaimStatus = Literal["verified", "unverified", "invalid"]


@dataclass(frozen=True)
class AnswerClaimCheck:
    status: ClaimStatus
    displayed_numbers: dict[str, Decimal]
    evidence_numbers: dict[str, Decimal]
    claim_count: int
    reason: str | None = None


def verify_answer_claims(view: AnalysisRunViewResponse) -> AnswerClaimCheck:
    """Fail closed for missing, malformed, or cross-artifact numeric claim references."""
    messages = [message for message in view.messages if message.role == "assistant"]
    if not messages:
        return _failed("unverified", "assistant_message_missing")
    message = messages[-1]
    raw_claims = message.context_patch.get("answer_claims")
    if raw_claims is None:
        return _failed("unverified", "answer_claims_missing")
    if not isinstance(raw_claims, list) or not raw_claims:
        return _failed("invalid", "answer_claims_malformed")

    artifacts = {item.id: item for item in view.artifacts}
    evidence = {item.id: item for item in view.evidence}
    validations = {item.id: item for item in view.validations}
    displayed: dict[str, Decimal] = {}
    sourced: dict[str, Decimal] = {}
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            return _failed("invalid", "answer_claim_malformed")
        column = raw_claim.get("column")
        value = raw_claim.get("value")
        if not isinstance(column, str) or not column or not isinstance(value, str):
            return _failed("invalid", "answer_claim_malformed")
        if column in displayed:
            return _failed("invalid", "answer_claim_duplicate_column")
        artifact_id = _parse_id(raw_claim.get("artifact_id"))
        evidence_id = _parse_id(raw_claim.get("evidence_id"))
        validation_id = _parse_id(raw_claim.get("validation_id"))
        if artifact_id is None or evidence_id is None or validation_id is None:
            return _failed("invalid", "answer_claim_reference_malformed")
        artifact = artifacts.get(artifact_id)
        source = evidence.get(evidence_id)
        validation = validations.get(validation_id)
        if (
            artifact is None
            or artifact.artifact_type != "query_result"
            or source is None
            or source.artifact_id != artifact_id
            or source.evidence_type != "query_execution"
            or validation is None
            or validation.validation_type != "evidence"
            or validation.outcome != "passed"
        ):
            return _failed("invalid", "answer_claim_reference_mismatch")
        columns = artifact.summary.get("columns")
        rows = artifact.summary.get("rows")
        if (
            not isinstance(columns, list)
            or not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], list)
            or columns.count(column) != 1
        ):
            return _failed("invalid", "answer_claim_source_ambiguous")
        index = columns.index(column)
        if index >= len(rows[0]):
            return _failed("invalid", "answer_claim_source_missing")
        try:
            displayed_number = Decimal(value)
            source_number = Decimal(str(rows[0][index]))
        except (InvalidOperation, ValueError, TypeError):
            return _failed("invalid", "answer_claim_not_numeric")
        if not displayed_number.is_finite() or not source_number.is_finite():
            return _failed("invalid", "answer_claim_not_finite")
        if displayed_number != source_number:
            return _failed("invalid", "answer_claim_value_mismatch")
        pattern = rf"(?<![0-9.]){re.escape(value)}(?![0-9.])"
        if re.search(pattern, message.content) is None:
            return _failed("invalid", "answer_claim_not_displayed")
        displayed[column] = displayed_number
        sourced[column] = source_number
    return AnswerClaimCheck("verified", displayed, sourced, len(raw_claims))


def _parse_id(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _failed(status: ClaimStatus, reason: str) -> AnswerClaimCheck:
    return AnswerClaimCheck(status, {}, {}, 0, reason)
