"""Normalize real system-gate probe evidence without retaining request or response bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from packages.evaluation.contracts import SafetyEntrypoint, SystemGateProof


@dataclass(frozen=True)
class SystemGateSnapshot:
    workspace_id: uuid.UUID
    validated_query_ids: frozenset[uuid.UUID]
    execution_ids: frozenset[uuid.UUID]
    run_ids: frozenset[uuid.UUID]
    artifact_ids: frozenset[uuid.UUID]


def build_system_gate_proof(
    *,
    entrypoint: SafetyEntrypoint,
    response_status: int,
    denial_code: str,
    response_text: str,
    protected_canaries: tuple[str, ...],
    authenticated_actor_id: uuid.UUID | None,
    expected_actor_id: uuid.UUID,
    requested_workspace_id: uuid.UUID,
    synthetic_workspace_ids: frozenset[uuid.UUID],
    before: SystemGateSnapshot | None,
    after: SystemGateSnapshot | None,
    executor_called: bool,
) -> SystemGateProof:
    """Build a fail-closed proof from an isolated, explicitly scoped API attempt."""
    if not protected_canaries or any(not canary for canary in protected_canaries):
        raise ValueError("a nonempty synthetic canary is required")
    snapshots_scoped = (
        before is not None
        and after is not None
        and before.workspace_id == requested_workspace_id
        and after.workspace_id == requested_workspace_id
    )
    return SystemGateProof(
        probe_kind="system_gate",
        entrypoint=entrypoint,
        response_status=response_status,
        denial_code=denial_code,
        identity_verified=(
            authenticated_actor_id is not None and authenticated_actor_id == expected_actor_id
        ),
        workspace_verified=(requested_workspace_id in synthetic_workspace_ids),
        correlation_verified=snapshots_scoped,
        response_data_exposed=any(
            canary in response_text for canary in protected_canaries if canary
        ),
        side_effects_checked=snapshots_scoped,
        side_effects_detected=(before != after) if snapshots_scoped else False,
        executor_called=executor_called,
    )
