"""Persisted semantic-state fixtures for the real Agent binding clarification path."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from apps.api.services.analysis_runs import create_run, get_run_view
from apps.worker.analysis_runtime import run_analysis
from packages.evaluation.contracts import EvaluationCase, ObservedOutcome
from packages.evaluation.observation import observe_clarification_run
from packages.evaluation.runner import OfflineCaseExecution
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.models import User, Workspace
from packages.semantic_model.manufacturing import manufacturing_quality_template
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelStatus,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.agents import CreateAnalysisRunRequest


@dataclass(frozen=True)
class SemanticAmbiguity:
    question: str
    metric: str
    count: int
    state: Literal["published", "draft", "foreign"] = "published"


SEMANTIC_AMBIGUITIES = {
    "ambiguity-unknown-quality-metric": SemanticAmbiguity("分析综合质量评分", "综合质量评分", 1),
    "ambiguity-unknown-production-metric": SemanticAmbiguity("分析产能饱和度", "产能饱和度", 1),
    "ambiguity-two-defect-definitions": SemanticAmbiguity("分析不良率", "不良率", 2),
    "ambiguity-two-inspection-definitions": SemanticAmbiguity("分析检验数量", "检验数量", 2),
    "ambiguity-three-defect-definitions": SemanticAmbiguity("分析不良率", "不良率", 3),
    "ambiguity-draft-only-definition": SemanticAmbiguity("分析不良率", "不良率", 1, "draft"),
    "ambiguity-foreign-definition": SemanticAmbiguity("分析不良率", "不良率", 1, "foreign"),
}


def pinned_semantic_ambiguity(case: EvaluationCase) -> SemanticAmbiguity | None:
    spec = SEMANTIC_AMBIGUITIES.get(case.id)
    return (
        spec if spec and case.category == "ambiguity" and case.turns == (spec.question,) else None
    )


def seed_semantics(
    db: Session, user: User, workspace: Workspace, spec: SemanticAmbiguity
) -> tuple[SemanticModel, ...]:
    target = workspace
    if spec.state == "foreign":
        target = Workspace(
            name="SYNTHETIC_PRIVATE_SEMANTIC_CANARY", slug=f"foreign-{uuid.uuid4().hex}"
        )
        db.add(target)
        db.flush()
    document = manufacturing_quality_template().model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    models = []
    for index in range(spec.count):
        model = SemanticModel(
            workspace_id=target.id,
            name=f"Synthetic definition {index}",
            status=SemanticModelStatus.DRAFT
            if spec.state == "draft"
            else SemanticModelStatus.PUBLISHED,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        db.add(model)
        db.flush()
        version = SemanticModelVersion(
            workspace_id=target.id,
            semantic_model_id=model.id,
            revision=1,
            status=SemanticVersionStatus.DRAFT
            if spec.state == "draft"
            else SemanticVersionStatus.PUBLISHED,
            document=document,
            content_digest=digest,
            created_by_user_id=user.id,
        )
        db.add(version)
        db.flush()
        if spec.state != "draft":
            model.active_version_id = version.id
        models.append(model)
    db.commit()
    return tuple(models)


class SemanticClarificationSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        spec = pinned_semantic_ambiguity(self.case)
        assert spec is not None
        models = seed_semantics(self.db, self.user, self.workspace, spec)
        run = create_run(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisRunRequest(message=spec.question),
        )
        gateway = FakeGateway(
            [
                GatewayResponse(
                    "offline-semantic-ambiguity",
                    "fake",
                    json.dumps(
                        {
                            "task_type": "metric_query",
                            "goal": spec.question,
                            "metrics": [spec.metric],
                            "confidence": 0.98,
                        },
                        ensure_ascii=False,
                    ),
                    None,
                    (),
                    "stop",
                    GatewayUsage(20, 10, 30),
                )
            ]
        )
        run_analysis(self.db, run_id=run.id, gateway=gateway)
        view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
        request = view.run.context.get("clarification")
        ambiguous = spec.count > 1 and spec.state == "published"
        expected_ids = {str(model.id) for model in models} if ambiguous else set()
        expected_reason = (
            "semantic_binding_ambiguous" if ambiguous else "semantic_binding_not_found"
        )
        expected_question = (
            f"“{spec.metric}”对应多个已发布口径，请选择一个。"
            if ambiguous
            else f"找不到“{spec.metric}”的唯一已发布口径，请更换指标或检查语义模型。"
        )
        correct = isinstance(request, dict) and (
            request.get("reason_code") == expected_reason
            and request.get("question") == expected_question
            and request.get("missing_fields") == ([] if ambiguous else ["metrics"])
            and request.get("resume_node") == "bind"
            and isinstance(request.get("candidates"), list)
            and {item.get("key") for item in request["candidates"]} == expected_ids
            and len(request["candidates"]) == len(expected_ids)
            and len(gateway.calls) == 1
        )
        if spec.state == "foreign":
            content = view.model_dump_json()
            correct = correct and "SYNTHETIC_PRIVATE_SEMANTIC_CANARY" not in content
            correct = correct and all(str(model.id) not in content for model in models)
        if view.run.status != "waiting_for_clarification" or not correct:
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        return OfflineCaseExecution(observe_clarification_run(view), (run.id,))
