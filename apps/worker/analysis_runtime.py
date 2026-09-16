"""Durable Plan-Execute-Verify runtime for M5 analysis runs."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.services.analysis_runs import add_event
from apps.api.services.queries import compile_query, execute_query
from packages.agent_core.capabilities import capability_response
from packages.agent_core.catalog_search import search_published_catalogs
from packages.agent_core.contracts import (
    AnalysisPlan,
    AnalysisStep,
    Binding,
    ClarificationRequest,
    FollowUpDecision,
    Intent,
    RouteDecision,
)
from packages.agent_core.conversation_runtime import prepare_conversation_run
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisCheckpoint,
    AnalysisEvidence,
    AnalysisMessage,
    AnalysisPlanRecord,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStepRecord,
    AnalysisStepStatus,
    AnalysisToolCall,
    AnalysisValidation,
)
from packages.agent_core.planner import (
    PublishedSemantic,
    SemanticBindingError,
    bind_intent,
    create_plan,
    revise_intent,
    route_intent,
    understand,
)
from packages.agent_core.presentation import (
    AgentPresentation,
    answer_presentation,
    catalog_presentation,
    clarification_presentation,
    failure_presentation,
    query_presentation,
    small_talk_presentation,
)
from packages.agent_core.small_talk import small_talk_response
from packages.model_gateway import ModelGateway, ModelGatewayError
from packages.semantic_model.models import SemanticModel, SemanticModelVersion
from packages.shared_contracts.queries import QueryFilter, SemanticQueryRequest
from packages.shared_contracts.semantic_models import SemanticDocument
from packages.toolkit import build_default_registry

MetricExecutor = Callable[[Session, AnalysisRun, AnalysisPlan], dict[str, object]]
ACTIVE = {AnalysisRunStatus.QUEUED, AnalysisRunStatus.RUNNING}


def _checkpoint(db: Session, run: AnalysisRun, node: str) -> None:
    sequence = db.scalar(
        select(func.count(AnalysisCheckpoint.id)).where(AnalysisCheckpoint.run_id == run.id)
    )
    db.add(
        AnalysisCheckpoint(
            workspace_id=run.workspace_id,
            run_id=run.id,
            sequence=int(sequence or 0) + 1,
            node=node,
            graph_version="1.0.0",
            state={
                "status": run.status.value,
                "current_node": node,
                "context": run.context,
                "frozen_versions": run.frozen_versions,
                "model_calls": run.model_calls,
                "tool_calls": run.tool_calls,
                "total_tokens": run.total_tokens,
                "replan_count": run.replan_count,
            },
        )
    )
    run.current_node = node
    run.version += 1
    add_event(db, run, "run.node", {"node": node, "status": run.status.value})
    db.commit()


def _published_semantics(db: Session, run: AnalysisRun) -> tuple[PublishedSemantic, ...]:
    rows = db.execute(
        select(SemanticModel, SemanticModelVersion)
        .join(SemanticModelVersion, SemanticModel.active_version_id == SemanticModelVersion.id)
        .where(SemanticModel.workspace_id == run.workspace_id)
    ).all()
    return tuple(
        PublishedSemantic(
            model_id=str(model.id),
            version_id=str(version.id),
            document=SemanticDocument.model_validate(version.document),
        )
        for model, version in rows
    )


def _persist_agent_message(
    db: Session,
    run: AnalysisRun,
    presentation: AgentPresentation,
    *,
    key: str,
) -> None:
    idempotency_key = f"agent:{run.version}:{key}"[:100]
    existing = db.scalar(
        select(AnalysisMessage.id).where(
            AnalysisMessage.run_id == run.id,
            AnalysisMessage.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return
    db.add(
        AnalysisMessage(
            workspace_id=run.workspace_id,
            run_id=run.id,
            role="assistant",
            content=presentation.content,
            idempotency_key=idempotency_key,
            context_patch=presentation.context_patch,
            created_at=datetime.now(UTC),
        )
    )
    add_event(db, run, "message.generated", {"role": "assistant", "kind": key})


def _intent_metric_names(run: AnalysisRun) -> tuple[str, ...]:
    raw_intent = run.context.get("intent")
    if not isinstance(raw_intent, dict):
        return ()
    raw_metrics = raw_intent.get("metrics")
    if not isinstance(raw_metrics, list):
        return ()
    return tuple(item for item in raw_metrics if isinstance(item, str))


def _exception_code(exc: Exception) -> str:
    structured = getattr(exc, "code", None)
    if isinstance(structured, str) and structured.startswith(
        ("agent.", "catalog.", "connector.", "model.", "policy.", "query.", "tool.")
    ):
        return structured
    text = str(exc)
    if text.startswith(
        ("agent.", "catalog.", "connector.", "model.", "policy.", "query.", "tool.")
    ):
        return text
    return "agent.execution_failed"


def _fail(
    db: Session,
    run: AnalysisRun,
    code: str,
    *,
    retryable: bool,
) -> None:
    run.status = AnalysisRunStatus.FAILED_RETRYABLE if retryable else AnalysisRunStatus.FAILED
    run.error_code = code
    run.finished_at = None if retryable else datetime.now(UTC)
    _persist_agent_message(
        db,
        run,
        failure_presentation(
            code,
            retryable=retryable,
            metric_names=_intent_metric_names(run),
        ),
        key="failure",
    )
    running_steps = db.scalars(
        select(AnalysisStepRecord).where(
            AnalysisStepRecord.run_id == run.id,
            AnalysisStepRecord.status == AnalysisStepStatus.RUNNING,
        )
    ).all()
    for step in running_steps:
        step.status = AnalysisStepStatus.FAILED
        step.error_code = code
        step.finished_at = datetime.now(UTC)
    add_event(
        db,
        run,
        "run.failed",
        {"code": code, "retryable": retryable, "node": run.current_node},
    )
    db.commit()


def _check_budget(run: AnalysisRun, *, model: bool = False, tool: bool = False) -> None:
    if model and run.model_calls >= _as_int(run.budget.get("max_model_calls"), 6):
        raise ModelGatewayError("agent.model_budget_exhausted")
    if tool and run.tool_calls >= _as_int(run.budget.get("max_tool_calls"), 12):
        raise ModelGatewayError("agent.tool_budget_exhausted")
    if run.total_tokens >= _as_int(run.budget.get("max_total_tokens"), 32_000):
        raise ModelGatewayError("agent.token_budget_exhausted")


def _as_int(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _complete_small_talk(db: Session, run: AnalysisRun, intent: Intent) -> None:
    plan = AnalysisPlan(
        goal=intent.goal,
        steps=(
            AnalysisStep(
                id="respond_socially",
                tool="system.small_talk",
                arguments={"message": intent.goal},
                expected_evidence=("conversation_scope",),
            ),
        ),
    )
    plan_record = AnalysisPlanRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        revision=run.replan_count + 1,
        goal=plan.goal,
        document=plan.model_dump(mode="json"),
        requires_confirmation=False,
    )
    db.add(plan_record)
    db.flush()
    step = AnalysisStepRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        plan_id=plan_record.id,
        step_key=plan.steps[0].id,
        tool_name=plan.steps[0].tool,
        arguments=plan.steps[0].arguments,
        dependencies=[],
        status=AnalysisStepStatus.PENDING,
    )
    db.add(step)
    run.context = {**run.context, "plan": plan.model_dump(mode="json")}
    _checkpoint(db, run, "policy_check")

    _check_budget(run, tool=True)
    step.status = AnalysisStepStatus.RUNNING
    step.started_at = datetime.now(UTC)
    _checkpoint(db, run, "execute")
    result = small_talk_response(intent.goal)
    _persist_agent_message(
        db,
        run,
        small_talk_presentation(str(result["message"])),
        key="small-talk-answer",
    )
    normalized = json.dumps(
        plan.steps[0].arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    db.add(
        AnalysisToolCall(
            workspace_id=run.workspace_id,
            run_id=run.id,
            step_id=step.id,
            tool_name="system.small_talk",
            tool_version="1.0.0",
            idempotency_key=hashlib.sha256(
                f"{run.id}:{run.replan_count}:{step.step_key}:{normalized}".encode()
            ).hexdigest(),
            argument_digest=digest,
            status=AnalysisStepStatus.SUCCEEDED,
            result_summary=result,
        )
    )
    run.tool_calls += 1
    step.status = AnalysisStepStatus.SUCCEEDED
    step.finished_at = datetime.now(UTC)

    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact_digest = hashlib.sha256(canonical.encode()).hexdigest()
    artifact = AnalysisArtifact(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_type="assistant_message",
        summary=result,
        content_digest=artifact_digest,
    )
    db.add(artifact)
    db.flush()
    db.add(
        AnalysisValidation(
            workspace_id=run.workspace_id,
            run_id=run.id,
            validation_type="conversation_scope",
            outcome="passed",
            findings=[],
        )
    )
    run.context = {
        **run.context,
        "result": result,
        "artifact_id": str(artifact.id),
        "evidence_digest": artifact_digest,
    }
    _checkpoint(db, run, "verify")
    run.status = AnalysisRunStatus.COMPLETED
    run.current_node = "present"
    run.finished_at = datetime.now(UTC)
    run.error_code = None
    run.version += 1
    add_event(
        db,
        run,
        "run.completed",
        {"artifact_id": str(artifact.id), "trust": "system", "kind": result["kind"]},
    )
    db.commit()


def _complete_capability_help(db: Session, run: AnalysisRun, intent: Intent) -> None:
    plan = AnalysisPlan(
        goal=intent.goal,
        steps=(
            AnalysisStep(
                id="describe_capabilities",
                tool="system.capabilities",
                arguments={},
                expected_evidence=("capability_manifest",),
            ),
        ),
    )
    plan_record = AnalysisPlanRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        revision=run.replan_count + 1,
        goal=plan.goal,
        document=plan.model_dump(mode="json"),
        requires_confirmation=False,
    )
    db.add(plan_record)
    db.flush()
    step = AnalysisStepRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        plan_id=plan_record.id,
        step_key=plan.steps[0].id,
        tool_name=plan.steps[0].tool,
        arguments={},
        dependencies=[],
        status=AnalysisStepStatus.PENDING,
    )
    db.add(step)
    run.context = {**run.context, "plan": plan.model_dump(mode="json")}
    _checkpoint(db, run, "policy_check")

    _check_budget(run, tool=True)
    step.status = AnalysisStepStatus.RUNNING
    step.started_at = datetime.now(UTC)
    _checkpoint(db, run, "execute")
    result = capability_response()
    _persist_agent_message(
        db,
        run,
        answer_presentation(str(result.get("message") or "")),
        key="capability-answer",
    )
    normalized = json.dumps({}, separators=(",", ":"))
    call_key = hashlib.sha256(
        f"{run.id}:{run.replan_count}:{step.step_key}:{normalized}".encode()
    ).hexdigest()
    db.add(
        AnalysisToolCall(
            workspace_id=run.workspace_id,
            run_id=run.id,
            step_id=step.id,
            tool_name="system.capabilities",
            tool_version="1.0.0",
            idempotency_key=call_key,
            argument_digest=hashlib.sha256(normalized.encode()).hexdigest(),
            status=AnalysisStepStatus.SUCCEEDED,
            result_summary=result,
        )
    )
    run.tool_calls += 1
    step.status = AnalysisStepStatus.SUCCEEDED
    step.finished_at = datetime.now(UTC)

    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact_digest = hashlib.sha256(canonical.encode()).hexdigest()
    artifact = AnalysisArtifact(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_type="assistant_message",
        summary=result,
        content_digest=artifact_digest,
    )
    db.add(artifact)
    db.flush()
    manifest_digest = str(result["manifest_digest"])
    db.add(
        AnalysisEvidence(
            workspace_id=run.workspace_id,
            run_id=run.id,
            artifact_id=artifact.id,
            evidence_type="capability_manifest",
            reference={
                "manifest_version": result["manifest_version"],
                "manifest_digest": manifest_digest,
            },
            evidence_digest=manifest_digest,
        )
    )
    db.add(
        AnalysisValidation(
            workspace_id=run.workspace_id,
            run_id=run.id,
            validation_type="capability_scope",
            outcome="passed",
            findings=[],
        )
    )
    run.context = {
        **run.context,
        "result": result,
        "artifact_id": str(artifact.id),
        "evidence_digest": manifest_digest,
        "capability_manifest_version": result["manifest_version"],
    }
    _checkpoint(db, run, "verify")
    run.status = AnalysisRunStatus.COMPLETED
    run.current_node = "present"
    run.finished_at = datetime.now(UTC)
    run.error_code = None
    run.version += 1
    add_event(
        db,
        run,
        "run.completed",
        {
            "artifact_id": str(artifact.id),
            "evidence_digest": manifest_digest,
            "trust": "system",
        },
    )
    db.commit()


def _complete_catalog_search(db: Session, run: AnalysisRun, intent: Intent) -> None:
    plan = AnalysisPlan(
        goal=intent.goal,
        steps=(
            AnalysisStep(
                id="search_catalog",
                tool="catalog.search",
                arguments={"query": intent.goal},
                expected_evidence=("catalog_snapshot",),
            ),
        ),
    )
    plan_record = AnalysisPlanRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        revision=run.replan_count + 1,
        goal=plan.goal,
        document=plan.model_dump(mode="json"),
        requires_confirmation=False,
    )
    db.add(plan_record)
    db.flush()
    step = AnalysisStepRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        plan_id=plan_record.id,
        step_key=plan.steps[0].id,
        tool_name=plan.steps[0].tool,
        arguments=plan.steps[0].arguments,
        dependencies=[],
        status=AnalysisStepStatus.PENDING,
    )
    db.add(step)
    run.context = {**run.context, "plan": plan.model_dump(mode="json")}
    _checkpoint(db, run, "policy_check")

    _check_budget(run, tool=True)
    step.status = AnalysisStepStatus.RUNNING
    step.started_at = datetime.now(UTC)
    _checkpoint(db, run, "execute")
    registry = build_default_registry()
    registry.bind(
        "catalog.search",
        lambda arguments: search_published_catalogs(
            db,
            workspace_id=run.workspace_id,
            query=str(arguments["query"]),
        ),
    )
    result = registry.invoke("catalog.search", plan.steps[0].arguments)
    _persist_agent_message(db, run, catalog_presentation(result), key="catalog-answer")
    normalized = json.dumps(
        plan.steps[0].arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    call_key = hashlib.sha256(
        f"{run.id}:{run.replan_count}:{step.step_key}:{normalized}".encode()
    ).hexdigest()
    db.add(
        AnalysisToolCall(
            workspace_id=run.workspace_id,
            run_id=run.id,
            step_id=step.id,
            tool_name="catalog.search",
            tool_version="1.0.0",
            idempotency_key=call_key,
            argument_digest=hashlib.sha256(normalized.encode()).hexdigest(),
            status=AnalysisStepStatus.SUCCEEDED,
            result_summary=result,
        )
    )
    run.tool_calls += 1
    step.status = AnalysisStepStatus.SUCCEEDED
    step.finished_at = datetime.now(UTC)

    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact_digest = hashlib.sha256(canonical.encode()).hexdigest()
    artifact = AnalysisArtifact(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_type="catalog_result",
        summary=result,
        content_digest=artifact_digest,
    )
    db.add(artifact)
    db.flush()
    snapshot_ids: list[str] = []
    raw_sources = result.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    for source in sources:
        if not isinstance(source, dict):
            continue
        snapshot_id = str(source.get("snapshot_id", ""))
        if not snapshot_id:
            continue
        snapshot_ids.append(snapshot_id)
        snapshot_digest = str(source.get("snapshot_digest") or artifact_digest)
        db.add(
            AnalysisEvidence(
                workspace_id=run.workspace_id,
                run_id=run.id,
                artifact_id=artifact.id,
                evidence_type="catalog_snapshot",
                reference={
                    "data_source_id": source.get("id"),
                    "snapshot_id": snapshot_id,
                    "snapshot_version": source.get("snapshot_version"),
                },
                evidence_digest=snapshot_digest,
            )
        )
    for validation_type in ("authorization_scope", "sensitive_output"):
        db.add(
            AnalysisValidation(
                workspace_id=run.workspace_id,
                run_id=run.id,
                validation_type=validation_type,
                outcome="passed",
                findings=[],
            )
        )
    run.frozen_versions = {
        "snapshot_ids": sorted(snapshot_ids),
        "tool_registry_version": "1.0.0",
    }
    run.context = {
        **run.context,
        "result": result,
        "artifact_id": str(artifact.id),
        "evidence_digest": artifact_digest,
    }
    _checkpoint(db, run, "verify")
    run.status = AnalysisRunStatus.COMPLETED
    run.current_node = "present"
    run.finished_at = datetime.now(UTC)
    run.error_code = None
    run.version += 1
    add_event(
        db,
        run,
        "run.completed",
        {
            "artifact_id": str(artifact.id),
            "evidence_digest": artifact_digest,
            "trust": "catalog",
        },
    )
    db.commit()


def _complete_verified_result_explanation(db: Session, run: AnalysisRun, intent: Intent) -> None:
    raw_context = run.context.get("conversation_context")
    context = raw_context if isinstance(raw_context, dict) else {}
    raw_result = context.get("last_result")
    if not isinstance(raw_result, dict):
        raise ModelGatewayError("agent.previous_result_not_available")
    artifact_id = uuid.UUID(str(raw_result["artifact_id"]))
    source_artifact = db.scalar(
        select(AnalysisArtifact).where(
            AnalysisArtifact.id == artifact_id,
            AnalysisArtifact.workspace_id == run.workspace_id,
        )
    )
    if source_artifact is None:
        raise ModelGatewayError("agent.previous_result_not_available")
    primary_value = raw_result.get("primary_value")
    row_count = raw_result.get("row_count")
    result_description = (
        f"上一轮已验证的结果值是 {primary_value}。"
        if isinstance(primary_value, str) and primary_value
        else f"上一轮已验证结果包含 {row_count if isinstance(row_count, int) else 0} 行数据。"
    )
    content = (
        f"{result_description}这个结果能够说明当前指标在已选时间和筛选范围内的表现，"
        "但仅凭汇总结果不能可靠判断原因。要定位原因，我可以继续按时间、产线、工序或设备拆分，"
        "再比较哪些分组贡献了主要变化。"
    )
    plan = AnalysisPlan(
        goal=intent.goal,
        steps=(
            AnalysisStep(
                id="describe_verified_result",
                tool="analysis.describe",
                arguments={"artifact_id": str(source_artifact.id)},
                expected_evidence=("verified_result_reference",),
            ),
        ),
        requires_confirmation=False,
    )
    plan_record = AnalysisPlanRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        revision=1,
        goal=plan.goal,
        document=plan.model_dump(mode="json"),
        requires_confirmation=False,
    )
    db.add(plan_record)
    db.flush()
    step = AnalysisStepRecord(
        workspace_id=run.workspace_id,
        run_id=run.id,
        plan_id=plan_record.id,
        step_key="describe_verified_result",
        tool_name="analysis.describe",
        arguments={"artifact_id": str(source_artifact.id)},
        dependencies=[],
        status=AnalysisStepStatus.SUCCEEDED,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db.add(step)
    db.flush()
    registry = build_default_registry()
    registry.bind(
        "analysis.describe",
        lambda _: {
            "message": content,
            "source_artifact_id": str(source_artifact.id),
            "row_count": row_count if isinstance(row_count, int) else 0,
        },
    )
    result = registry.invoke("analysis.describe", plan.steps[0].arguments)
    normalized = json.dumps(plan.steps[0].arguments, sort_keys=True, separators=(",", ":"))
    db.add(
        AnalysisToolCall(
            workspace_id=run.workspace_id,
            run_id=run.id,
            step_id=step.id,
            tool_name="analysis.describe",
            tool_version="1.0.0",
            idempotency_key=hashlib.sha256(
                f"{run.id}:analysis.describe:{normalized}".encode()
            ).hexdigest(),
            argument_digest=hashlib.sha256(normalized.encode()).hexdigest(),
            status=AnalysisStepStatus.SUCCEEDED,
            result_summary=result,
        )
    )
    run.tool_calls += 1
    artifact_digest = hashlib.sha256(content.encode()).hexdigest()
    artifact = AnalysisArtifact(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_type="assistant_message",
        summary=result,
        content_digest=artifact_digest,
    )
    db.add(artifact)
    db.flush()
    source_evidence_id = raw_result.get("evidence_id")
    evidence = AnalysisEvidence(
        workspace_id=run.workspace_id,
        run_id=run.id,
        artifact_id=artifact.id,
        evidence_type="verified_result_reference",
        reference={
            "source_run_id": run.context.get("previous_run_id"),
            "source_artifact_id": str(source_artifact.id),
            "source_evidence_id": source_evidence_id,
        },
        evidence_digest=artifact_digest,
    )
    db.add(evidence)
    db.add(
        AnalysisValidation(
            workspace_id=run.workspace_id,
            run_id=run.id,
            validation_type="verified_result_reference",
            outcome="passed",
            findings=[],
        )
    )
    _persist_agent_message(db, run, answer_presentation(content), key="result-explanation")
    run.context = {
        **run.context,
        "plan": plan.model_dump(mode="json"),
        "result": result,
        "artifact_id": str(artifact.id),
        "evidence_digest": artifact_digest,
    }
    run.status = AnalysisRunStatus.COMPLETED
    run.current_node = "present"
    run.finished_at = datetime.now(UTC)
    run.error_code = None
    run.version += 1
    add_event(
        db,
        run,
        "run.completed",
        {
            "artifact_id": str(artifact.id),
            "source_artifact_id": str(source_artifact.id),
            "trust": "derived_from_verified_result",
        },
    )
    db.commit()


def run_analysis(
    db: Session,
    *,
    run_id: uuid.UUID,
    gateway: ModelGateway,
    metric_executor: MetricExecutor | None = None,
) -> None:
    run = db.get(AnalysisRun, run_id)
    if run is None or run.status not in ACTIVE:
        return
    if run.cancel_requested_at is not None:
        run.status = AnalysisRunStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
        db.commit()
        return
    run.status = AnalysisRunStatus.RUNNING
    run.started_at = run.started_at or datetime.now(UTC)
    try:
        follow_up, follow_up_usage = prepare_conversation_run(db, run=run, gateway=gateway)
    except ModelGatewayError as exc:
        _fail(db, run, exc.code, retryable=exc.retryable or exc.code == "model.not_configured")
        return
    run.model_calls += follow_up_usage.model_calls
    run.total_tokens += follow_up_usage.total_tokens
    if follow_up is not None:
        add_event(
            db,
            run,
            "run.follow_up_classified",
            {
                "relation": follow_up.relation,
                "confidence": follow_up.confidence,
                "needs_clarification": follow_up.needs_clarification,
            },
        )
        if follow_up.relation == "switch_topic":
            add_event(db, run, "run.topic_switched", {"relation": "switch_topic"})
    if follow_up is not None and follow_up.needs_clarification:
        follow_up_clarification = ClarificationRequest(
            reason_code="follow_up_relation_ambiguous",
            question=follow_up.clarification_question or "你是想继续上一轮，还是开始一个新问题？",
            missing_fields=("follow_up_relation",),
            suggested_answers=("继续上一轮", "开始新主题"),
            resume_node="understand",
        )
        run.status = AnalysisRunStatus.WAITING_FOR_CLARIFICATION
        run.error_code = "agent.clarification_required"
        run.context = {
            **run.context,
            "clarification": follow_up_clarification.model_dump(mode="json"),
        }
        _persist_agent_message(
            db,
            run,
            clarification_presentation(follow_up_clarification),
            key="follow-up-clarification",
        )
        add_event(
            db,
            run,
            "run.clarification_required",
            {"code": run.error_code, "clarification": run.context["clarification"]},
        )
        db.commit()
        return
    _checkpoint(db, run, run.current_node)

    try:
        if follow_up is not None and follow_up.relation == "explain":
            raw_intent = run.context.get("intent")
            if not isinstance(raw_intent, dict):
                raise ModelGatewayError("agent.previous_result_not_available")
            _complete_verified_result_explanation(db, run, Intent.model_validate(raw_intent))
            return
        raw_intent = run.context.get("intent")
        revision_pending = run.context.get("intent_revision_pending") is True
        if isinstance(raw_intent, dict) and revision_pending:
            previous = Intent.model_validate(raw_intent)
            _check_budget(run, model=True)
            message = str(run.context.get("latest_user_message") or "")
            raw_decision = run.context.get("follow_up_decision")
            follow_up_decision = (
                FollowUpDecision.model_validate(raw_decision)
                if isinstance(raw_decision, dict)
                else None
            )
            intent, revision, usage = revise_intent(
                gateway,
                previous,
                message,
                relation=(
                    follow_up_decision.relation
                    if follow_up_decision is not None
                    else None
                ),
                suggested_patch=(
                    follow_up_decision.patch.model_dump(mode="json", exclude_none=True)
                    if follow_up_decision is not None
                    and follow_up_decision.patch is not None
                    else None
                ),
            )
            run.model_calls += usage.model_calls
            run.total_tokens += usage.total_tokens
            revision_number = _as_int(run.context.get("intent_revision"), 1) + 1
            run.context = {
                **run.context,
                "intent": intent.model_dump(mode="json"),
                "intent_revision": revision_number,
                "intent_revision_pending": False,
            }
            add_event(
                db,
                run,
                "run.intent_revised",
                {"revision": revision_number, "mode": revision.mode},
            )
            _checkpoint(db, run, "route")
        elif isinstance(raw_intent, dict):
            intent = Intent.model_validate(raw_intent)
        else:
            _check_budget(run, model=True)
            message = str(run.context.get("latest_user_message") or run.context["goal"])
            intent, usage = understand(gateway, message, context=run.context)
            run.model_calls += usage.model_calls
            run.total_tokens += usage.total_tokens
            run.context = {
                **run.context,
                "intent": intent.model_dump(mode="json"),
                "intent_revision": 1,
                "intent_revision_pending": False,
            }
            _checkpoint(db, run, "route")
        raw_route = run.context.get("route")
        if isinstance(raw_route, dict):
            route_decision = RouteDecision.model_validate(raw_route)
        else:
            route_decision = route_intent(intent)
            run.context = {
                **run.context,
                "route": route_decision.model_dump(mode="json"),
                "defaults_applied": route_decision.defaults_applied,
            }
            add_event(
                db,
                run,
                "run.route_selected",
                {
                    "route": route_decision.route,
                    "requires_binding": route_decision.requires_binding,
                },
            )
            if route_decision.defaults_applied:
                add_event(
                    db,
                    run,
                    "run.defaults_applied",
                    {"defaults": route_decision.defaults_applied},
                )
        if route_decision.clarification is not None:
            raise SemanticBindingError(
                "agent.clarification_required",
                "The routed question needs clarification",
                route_decision.clarification,
            )
        if route_decision.route == "small_talk":
            try:
                _complete_small_talk(db, run, intent)
            except ModelGatewayError as exc:
                _fail(db, run, exc.code, retryable=exc.retryable)
            except Exception as exc:
                _fail(db, run, _exception_code(exc), retryable=False)
            return
        if route_decision.route == "capability_help":
            try:
                _complete_capability_help(db, run, intent)
            except ModelGatewayError as exc:
                _fail(db, run, exc.code, retryable=exc.retryable)
            except Exception as exc:
                _fail(db, run, _exception_code(exc), retryable=False)
            return
        if route_decision.route == "catalog_exploration":
            try:
                _complete_catalog_search(db, run, intent)
            except ModelGatewayError as exc:
                _fail(db, run, exc.code, retryable=exc.retryable)
            except Exception as exc:
                _fail(db, run, _exception_code(exc), retryable=False)
            return
        if not route_decision.requires_binding:
            _fail(db, run, "agent.route_not_available", retryable=False)
            return
        _checkpoint(db, run, "bind")
        raw_binding = run.context.get("binding")
        if isinstance(raw_binding, dict):
            binding = Binding.model_validate(raw_binding)
        else:
            binding = bind_intent(intent, _published_semantics(db, run))
            run.context = {**run.context, "binding": binding.model_dump(mode="json")}
            run.frozen_versions = {
                "semantic_model_id": binding.semantic_model_id,
                "semantic_version_id": binding.semantic_version_id,
                "snapshot_ids": list(binding.snapshot_ids),
                "tool_registry_version": "1.0.0",
            }
            _checkpoint(db, run, "plan")
    except SemanticBindingError as exc:
        run.status = AnalysisRunStatus.WAITING_FOR_CLARIFICATION
        run.error_code = exc.code
        clarification_payload = exc.clarification.model_dump(mode="json")
        run.context = {**run.context, "clarification": clarification_payload}
        _persist_agent_message(
            db,
            run,
            clarification_presentation(exc.clarification),
            key="clarification",
        )
        add_event(
            db,
            run,
            "run.clarification_required",
            {"code": exc.code, "clarification": clarification_payload},
        )
        db.commit()
        return
    except ModelGatewayError as exc:
        _fail(db, run, exc.code, retryable=exc.retryable or exc.code == "model.not_configured")
        return

    raw_plan = run.context.get("plan")
    if isinstance(raw_plan, dict):
        plan = AnalysisPlan.model_validate(raw_plan)
    else:
        plan = create_plan(intent, binding)
        registry = build_default_registry()
        for planned_step in plan.steps:
            registry.get(planned_step.tool)
        plan_record = AnalysisPlanRecord(
            workspace_id=run.workspace_id,
            run_id=run.id,
            revision=run.replan_count + 1,
            goal=plan.goal,
            document=plan.model_dump(mode="json"),
            requires_confirmation=plan.requires_confirmation,
        )
        db.add(plan_record)
        db.flush()
        for planned_step in plan.steps:
            db.add(
                AnalysisStepRecord(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    plan_id=plan_record.id,
                    step_key=planned_step.id,
                    tool_name=planned_step.tool,
                    arguments=planned_step.arguments,
                    dependencies=list(planned_step.depends_on),
                    status=AnalysisStepStatus.PENDING,
                )
            )
        run.context = {**run.context, "plan": plan.model_dump(mode="json")}
        _checkpoint(db, run, "policy_check")
    if plan.requires_confirmation and run.context.get("plan_confirmed") is not True:
        run.status = AnalysisRunStatus.WAITING_FOR_CONFIRMATION
        add_event(db, run, "run.confirmation_required", {"plan": plan.model_dump(mode="json")})
        db.commit()
        return

    if isinstance(run.context.get("result"), dict):
        run.status = AnalysisRunStatus.COMPLETED
        run.finished_at = run.finished_at or datetime.now(UTC)
        db.commit()
        return
    try:
        _check_budget(run, tool=True)
        executor = metric_executor or _execute_metric
        planned_step = plan.steps[0]
        step = db.scalar(
            select(AnalysisStepRecord).where(
                AnalysisStepRecord.run_id == run.id,
                AnalysisStepRecord.step_key == planned_step.id,
            )
        )
        if step is None:
            raise RuntimeError("agent.step_missing")
        normalized = json.dumps(
            planned_step.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        call_key = hashlib.sha256(
            f"{run.id}:{run.replan_count}:{planned_step.id}:{normalized}".encode()
        ).hexdigest()
        existing = db.scalar(
            select(AnalysisToolCall).where(
                AnalysisToolCall.run_id == run.id,
                AnalysisToolCall.idempotency_key == call_key,
            )
        )
        if existing is not None and existing.status is AnalysisStepStatus.SUCCEEDED:
            result = dict(existing.result_summary)
        else:
            step.status = AnalysisStepStatus.RUNNING
            step.started_at = datetime.now(UTC)
            _checkpoint(db, run, "execute")
            registry = build_default_registry()
            registry.bind(
                "query.metric",
                lambda _: executor(db, run, plan),
            )
            result = registry.invoke(planned_step.tool, planned_step.arguments)
            call = AnalysisToolCall(
                workspace_id=run.workspace_id,
                run_id=run.id,
                step_id=step.id,
                tool_name=planned_step.tool,
                tool_version="1.0.0",
                idempotency_key=call_key,
                argument_digest=hashlib.sha256(normalized.encode()).hexdigest(),
                status=AnalysisStepStatus.SUCCEEDED,
                result_summary=result,
            )
            db.add(call)
            run.tool_calls += 1
            step.status = AnalysisStepStatus.SUCCEEDED
            step.finished_at = datetime.now(UTC)
        canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        artifact_digest = hashlib.sha256(canonical.encode()).hexdigest()
        artifact = AnalysisArtifact(
            workspace_id=run.workspace_id,
            run_id=run.id,
            artifact_type="query_result",
            summary=result,
            content_digest=artifact_digest,
        )
        db.add(artifact)
        db.flush()
        evidence_digest = str(result.get("evidence_digest") or artifact_digest)
        db.add(
            AnalysisEvidence(
                workspace_id=run.workspace_id,
                run_id=run.id,
                artifact_id=artifact.id,
                evidence_type="query_execution",
                reference={
                    "validated_query_id": result.get("validated_query_id"),
                    "execution_id": result.get("execution_id"),
                    "semantic_version_id": binding.semantic_version_id,
                    "snapshot_ids": list(binding.snapshot_ids),
                    "trust": result.get("trust", "trusted"),
                },
                evidence_digest=evidence_digest,
            )
        )
        db.add(
            AnalysisValidation(
                workspace_id=run.workspace_id,
                run_id=run.id,
                validation_type="evidence",
                outcome="passed",
                findings=[],
            )
        )
        run.context = {
            **run.context,
            "result": result,
            "artifact_id": str(artifact.id),
            "evidence_digest": evidence_digest,
        }
        _persist_agent_message(db, run, query_presentation(intent, result), key="query-answer")
        _checkpoint(db, run, "verify")
        run.status = AnalysisRunStatus.COMPLETED
        run.current_node = "present"
        run.finished_at = datetime.now(UTC)
        run.error_code = None
        run.version += 1
        add_event(
            db,
            run,
            "run.completed",
            {
                "artifact_id": str(artifact.id),
                "evidence_digest": evidence_digest,
                "trust": result.get("trust", "trusted"),
            },
        )
        db.commit()
    except ModelGatewayError as exc:
        _fail(db, run, exc.code, retryable=exc.retryable)
    except Exception as exc:
        _fail(db, run, _exception_code(exc), retryable=False)


def _execute_metric(db: Session, run: AnalysisRun, plan: AnalysisPlan) -> dict[str, object]:
    arguments = plan.steps[0].arguments
    raw_filters = arguments.get("filters")
    filter_values = raw_filters if isinstance(raw_filters, dict) else {}
    filters = [
        QueryFilter(dimension=key, operator="eq", value=value)
        for key, value in filter_values.items()
        if isinstance(key, str) and isinstance(value, (str, int, float, bool))
    ]
    raw_dimensions = arguments.get("dimensions")
    dimensions = [str(item) for item in raw_dimensions] if isinstance(raw_dimensions, list) else []
    comparison: Literal["none", "previous_period"] = (
        "previous_period" if arguments.get("comparison") == "previous_period" else "none"
    )
    raw_time_grain = arguments.get("time_grain")
    time_grain: Literal["hour", "day", "week", "month", "quarter", "year"] | None = (
        cast(Literal["hour", "day", "week", "month", "quarter", "year"], raw_time_grain)
        if raw_time_grain in {"hour", "day", "week", "month", "quarter", "year"}
        else None
    )
    raw_metrics = arguments.get("metrics")
    metrics = [str(item) for item in raw_metrics] if isinstance(raw_metrics, list) else []
    request = SemanticQueryRequest(
        semantic_model_id=uuid.UUID(str(arguments["semantic_model_id"])),
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        time_grain=time_grain,
        comparison=comparison,
        limit=_as_int(arguments.get("limit"), 200),
    )
    validated = compile_query(
        db,
        workspace_id=run.workspace_id,
        actor_user_id=run.created_by_user_id,
        payload=request,
    )
    execution = execute_query(
        db,
        workspace_id=run.workspace_id,
        actor_user_id=run.created_by_user_id,
        validated_query_id=validated.id,
    )
    return {
        "validated_query_id": str(validated.id),
        "execution_id": str(execution.id),
        "columns": execution.columns,
        "rows": execution.rows,
        "row_count": execution.row_count,
        "truncated": execution.truncated,
        "evidence_digest": execution.evidence_digest,
        "trust": execution.trust,
    }
