"""Bind advanced tools only with a caller-supplied, current-authorizing source loader."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from packages.analysis_engine.advanced import (
    AdvancedAnalysisError,
    CorrelationRequest,
    IQRRequest,
    correlate_verified_result,
    detect_iqr_anomalies,
)
from packages.toolkit import ToolRegistry, ToolRegistryError


@dataclass(frozen=True)
class VerifiedAnalysisInput:
    """Loader must check current workspace permission, provenance and source versions.

    This value is internal, not a request body. The binding checks identity/content,
    but cannot establish authorization from a digest or from this dataclass alone.
    """

    artifact_id: uuid.UUID
    evidence_id: uuid.UUID
    data: dict[str, object]
    content_digest: str


VerifiedSourceLoader = Callable[[uuid.UUID], VerifiedAnalysisInput]


def _load_verified(loader: VerifiedSourceLoader, artifact_id: uuid.UUID) -> VerifiedAnalysisInput:
    source = loader(artifact_id)
    if source.artifact_id != artifact_id:
        raise AdvancedAnalysisError("analysis.source_mismatch", "分析数据引用不一致，请重新查询。")
    try:
        encoded = json.dumps(
            source.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdvancedAnalysisError("analysis.invalid_table", "数据包含不合法的值。") from exc
    if hashlib.sha256(encoded).hexdigest() != source.content_digest:
        raise AdvancedAnalysisError("analysis.digest_mismatch", "数据内容校验失败，请重新查询。")
    return source


def bind_advanced_analysis_tools(registry: ToolRegistry, loader: VerifiedSourceLoader) -> None:
    def correlate(arguments: dict[str, object]) -> dict[str, object]:
        try:
            request = CorrelationRequest.model_validate(arguments)
        except ValidationError as exc:
            raise ToolRegistryError("tool.invalid_arguments") from exc
        source = _load_verified(loader, request.artifact_id)
        result = correlate_verified_result(source.data, request).model_dump(mode="json")
        return {
            **result,
            "source_evidence_id": str(source.evidence_id),
            "source_content_digest": source.content_digest,
        }

    def detect_anomaly(arguments: dict[str, object]) -> dict[str, object]:
        try:
            request = IQRRequest.model_validate(arguments)
        except ValidationError as exc:
            raise ToolRegistryError("tool.invalid_arguments") from exc
        source = _load_verified(loader, request.artifact_id)
        result = detect_iqr_anomalies(source.data, request).model_dump(mode="json")
        return {
            **result,
            "source_evidence_id": str(source.evidence_id),
            "source_content_digest": source.content_digest,
        }

    registry.bind("analysis.correlate", correlate)
    registry.bind("analysis.detect_anomaly", detect_anomaly)
