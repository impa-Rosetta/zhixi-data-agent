"""Strict tool boundary and trusted-loader contract; not production authorization proof."""

import hashlib
import json
import uuid

import pytest

from packages.analysis_engine.advanced import AdvancedAnalysisError
from packages.analysis_engine.tools import VerifiedAnalysisInput, bind_advanced_analysis_tools
from packages.toolkit import ToolRegistryError, build_default_registry


def fixture_input() -> VerifiedAnalysisInput:
    data: dict[str, object] = {
        "columns": ["x", "y"],
        "rows": [[i, i * 2] for i in range(10)],
        "row_count": 10,
        "truncated": False,
    }
    digest = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return VerifiedAnalysisInput(uuid.uuid4(), uuid.uuid4(), data, digest)


@pytest.mark.parametrize("tool", ["analysis.correlate", "analysis.detect_anomaly"])
def test_default_registry_does_not_claim_unbound_tools_available(tool: str) -> None:
    with pytest.raises(ToolRegistryError, match="tool.not_available"):
        build_default_registry().invoke(tool, {"artifact_id": str(uuid.uuid4())})


def test_registry_schemas_are_real_strict_protocols() -> None:
    registry = build_default_registry()
    schema = registry.get("analysis.correlate").input_schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"artifact_id", "x_field", "y_field"}
    assert registry.get("analysis.correlate").version == "1.1.0"
    assert registry.get("analysis.detect_anomaly").input_schema["additionalProperties"] is False


def test_bound_tools_load_authorized_reference_and_return_real_evidence() -> None:
    source = fixture_input()
    calls: list[uuid.UUID] = []

    def loader(artifact_id: uuid.UUID) -> VerifiedAnalysisInput:
        calls.append(artifact_id)
        return source

    registry = build_default_registry()
    bind_advanced_analysis_tools(registry, loader)
    result = registry.invoke(
        "analysis.correlate",
        {"artifact_id": str(source.artifact_id), "x_field": "x", "y_field": "y"},
    )
    assert result["coefficient"] == pytest.approx(1)
    assert result["source_evidence_id"] == str(source.evidence_id)
    assert result["source_content_digest"] == source.content_digest
    anomaly = registry.invoke(
        "analysis.detect_anomaly", {"artifact_id": str(source.artifact_id), "field": "y"}
    )
    assert anomaly["method"] == "iqr"
    assert anomaly["anomalies"] == []
    assert calls == [source.artifact_id, source.artifact_id]


@pytest.mark.parametrize(
    "updates",
    [{"code": "print(1)"}, {"artifact_id": "../secret"}, {"method": "eval"}, {"x_field": 42}],
)
def test_invalid_arguments_rejected_before_loader(updates) -> None:
    source = fixture_input()
    calls = []
    registry = build_default_registry()

    def loader(artifact_id: uuid.UUID) -> VerifiedAnalysisInput:
        calls.append(artifact_id)
        return source

    bind_advanced_analysis_tools(registry, loader)
    with pytest.raises(ToolRegistryError, match="tool.invalid_arguments"):
        registry.invoke(
            "analysis.correlate",
            {"artifact_id": str(source.artifact_id), "x_field": "x", "y_field": "y", **updates},
        )
    assert calls == []


def test_loader_permission_denial_is_not_swallowed_or_replaced_with_fake_output() -> None:
    registry = build_default_registry()

    def loader(artifact_id: uuid.UUID) -> VerifiedAnalysisInput:
        raise AdvancedAnalysisError("policy.denied", "没有权限")

    bind_advanced_analysis_tools(registry, loader)
    with pytest.raises(AdvancedAnalysisError, match="policy.denied"):
        registry.invoke("analysis.detect_anomaly", {"artifact_id": str(uuid.uuid4()), "field": "x"})


def test_loader_cannot_substitute_another_artifact() -> None:
    registry = build_default_registry()
    bind_advanced_analysis_tools(registry, lambda _: fixture_input())
    with pytest.raises(AdvancedAnalysisError, match="analysis.source_mismatch"):
        registry.invoke("analysis.detect_anomaly", {"artifact_id": str(uuid.uuid4()), "field": "x"})


def test_digest_mismatch_rejects_mutated_data() -> None:
    source = fixture_input()
    source.data["rows"] = [[i, 100] for i in range(10)]
    registry = build_default_registry()
    bind_advanced_analysis_tools(registry, lambda _: source)
    with pytest.raises(AdvancedAnalysisError, match="analysis.digest_mismatch"):
        registry.invoke(
            "analysis.detect_anomaly", {"artifact_id": str(source.artifact_id), "field": "y"}
        )
