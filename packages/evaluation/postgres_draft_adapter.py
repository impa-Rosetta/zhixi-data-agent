"""Pinned synthetic PostgreSQL cases using the real Agent query execution path.

Only fixed public fixture endpoints are supported. Never load a production URL.
Each case owns one temporary schema; source tables remain read-only and unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from apps.api.services.analysis_conversations import create_conversation, send_conversation_message
from apps.api.services.analysis_runs import create_run, get_run_view
from apps.api.services.semantic_models import create_semantic_model, publish_semantic_model
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.conversation_runtime import synchronize_conversation_after_run
from packages.agent_core.persistence import AnalysisRun, AnalysisTurn
from packages.connectors.base import ConnectionTarget, ConnectorCredentials
from packages.connectors.metadata import MetadataScanOptions
from packages.connectors.postgresql import PostgreSQLConnector
from packages.evaluation.contracts import EvaluationCase, ObservedOutcome
from packages.evaluation.draft_adapter import draft_case_factory
from packages.evaluation.equipment_metric_fixture import (
    EXTRA_EQUIPMENT_MAPPINGS,
    create_equipment_fixture,
    pinned_equipment_metric,
)
from packages.evaluation.observation import observe_completed_run
from packages.evaluation.production_boundary_fixture import (
    create_production_fixture,
    pinned_production_boundary,
)
from packages.evaluation.quality_metric_fixture import (
    EXTRA_QUALITY_MAPPINGS,
    QualityMetricSpec,
    create_quality_fixture,
    pinned_quality_metric,
)
from packages.evaluation.runner import OfflineCaseExecution, OfflineCaseSession
from packages.evaluation.versions import OFFLINE_TOOL_VERSION
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.catalog_store import object_counts, replace_snapshot_document
from packages.platform_core.database import Base
from packages.platform_core.models import (
    CatalogColumn,
    CatalogRelation,
    CatalogSnapshot,
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    DataSourceType,
    NetworkPolicy,
    SnapshotStatus,
    TlsMode,
    User,
    Workspace,
)
from packages.platform_core.network_policy import NetworkPolicyRules
from packages.platform_core.secrets import EnvelopeSecretProvider, secret_aad
from packages.platform_core.settings import get_settings
from packages.semantic_model.manufacturing import manufacturing_quality_template
from packages.shared_contracts.agents import (
    AnalysisRunViewResponse,
    CreateAnalysisConversationRequest,
    CreateAnalysisRunRequest,
    SendAnalysisConversationMessageRequest,
)
from packages.shared_contracts.semantic_models import PhysicalMapping

ADAPTER_VERSION = OFFLINE_TOOL_VERSION
ConversationPhase = Literal[
    "trend", "refine", "explain", "social", "september", "august", "recent", "switch_metric"
]


@dataclass(frozen=True)
class MultiturnSpec:
    turns: tuple[str, ...]
    metric_name: str
    metric_key: str
    phases: tuple[ConversationPhase, ...]


MULTITURN_CASES = {
    "multiturn-trend-then-monthly": MultiturnSpec(
        ("最近三个月不良率趋势", "按月份展开"),
        "不良率",
        "defect_rate",
        ("trend", "refine"),
    ),
    "multiturn-inspection-count-then-monthly": MultiturnSpec(
        ("最近三个月检验数量趋势", "按月份展开"),
        "检验数量",
        "inspected_quantity",
        ("trend", "refine"),
    ),
    "multiturn-production-count-then-monthly": MultiturnSpec(
        ("最近三个月生产产量趋势", "按月份展开"),
        "生产产量",
        "production_quantity",
        ("trend", "refine"),
    ),
    "multiturn-defect-trend-explain": MultiturnSpec(
        ("最近三个月不良率趋势", "解释一下"),
        "不良率",
        "defect_rate",
        ("trend", "explain"),
    ),
    "multiturn-defect-social-then-refine": MultiturnSpec(
        ("最近三个月不良率趋势", "你好", "按月份展开"),
        "不良率",
        "defect_rate",
        ("trend", "social", "refine"),
    ),
}
MULTITURN_CASES.update(
    {
        "multiturn-narrow-month": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月"),
            "不良率",
            "defect_rate",
            ("trend", "september"),
        ),
        "multiturn-replace-month": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月", "改成2026年8月"),
            "不良率",
            "defect_rate",
            ("trend", "september", "august"),
        ),
        "multiturn-reset-range": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月", "改成最近三个月"),
            "不良率",
            "defect_rate",
            ("trend", "september", "recent"),
        ),
        "multiturn-replace-metric": MultiturnSpec(
            ("最近三个月不良率趋势", "改成检验数量"),
            "不良率",
            "defect_rate",
            ("trend", "switch_metric"),
        ),
        "multiturn-narrow-then-explain": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月", "解释一下"),
            "不良率",
            "defect_rate",
            ("trend", "september", "explain"),
        ),
        "multiturn-replace-metric-retains-month": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月", "改成检验数量"),
            "不良率",
            "defect_rate",
            ("trend", "september", "switch_metric"),
        ),
        "multiturn-social-retains-narrowed-month": MultiturnSpec(
            ("最近三个月不良率趋势", "只看2026年9月", "你好", "按月份展开"),
            "不良率",
            "defect_rate",
            ("trend", "september", "social", "refine"),
        ),
    }
)
FIXTURE_URL = (
    "postgresql+psycopg://source_admin:source-admin-local-only@source-evaluation:5432/factory_demo"
)
MULTITURN_CASES.update(
    {
        "multiturn-quality-qualified-monthly": MultiturnSpec(
            ("最近三个月合格数量趋势", "按月份展开"),
            "合格数量",
            "qualified_quantity",
            ("trend", "refine"),
        ),
        "multiturn-quality-first-pass-monthly": MultiturnSpec(
            ("最近三个月一次通过率趋势", "按月份展开"),
            "一次通过率",
            "first_pass_yield",
            ("trend", "refine"),
        ),
        "multiturn-quality-scrap-explain": MultiturnSpec(
            ("最近三个月报废率趋势", "解释一下"), "报废率", "scrap_rate", ("trend", "explain")
        ),
        "multiturn-quality-rework-monthly": MultiturnSpec(
            ("最近三个月返工率趋势", "按月份展开"), "返工率", "rework_rate", ("trend", "refine")
        ),
        "multiturn-quality-pass-social": MultiturnSpec(
            ("最近三个月检验合格率趋势", "你好", "按月份展开"),
            "检验合格率",
            "inspection_pass_rate",
            ("trend", "social", "refine"),
        ),
        "multiturn-quality-ppm-narrow-explain": MultiturnSpec(
            ("最近三个月百万件缺陷数趋势", "只看2026年9月", "解释一下"),
            "百万件缺陷数",
            "defect_ppm",
            ("trend", "september", "explain"),
        ),
    }
)
MULTITURN_CASES.update(
    {
        "multiturn-completion-rate-monthly": MultiturnSpec(
            ("最近三个月计划达成率趋势", "按月份展开"),
            "计划达成率",
            "plan_completion_rate",
            ("trend", "refine"),
        ),
        "multiturn-completion-rate-explain": MultiturnSpec(
            ("最近三个月计划达成率趋势", "解释一下"),
            "计划达成率",
            "plan_completion_rate",
            ("trend", "explain"),
        ),
    }
)
MONTH_CASES = {
    "standard-july-defect-rate": ("2026年7月的不良率是多少？", "2026年7月", "不良率"),
    "standard-august-defect-rate": ("2026年8月的不良率是多少？", "2026年8月", "不良率"),
    "standard-september-defect-rate": ("2026年9月的不良率是多少？", "2026年9月", "不良率"),
    "standard-july-inspected-quantity": ("2026年7月的检验数量是多少？", "2026年7月", "检验数量"),
    "standard-august-inspected-quantity": ("2026年8月的检验数量是多少？", "2026年8月", "检验数量"),
    "standard-september-inspected-quantity": (
        "2026年9月的检验数量是多少？",
        "2026年9月",
        "检验数量",
    ),
    "standard-july-defect-quantity": ("2026年7月的缺陷数量是多少？", "2026年7月", "缺陷数量"),
    "standard-august-defect-quantity": ("2026年8月的缺陷数量是多少？", "2026年8月", "缺陷数量"),
    "standard-september-defect-quantity": ("2026年9月的缺陷数量是多少？", "2026年9月", "缺陷数量"),
    "standard-2025-oct-production-quantity": (
        "2025年10月的生产产量是多少？",
        "2025年10月",
        "生产产量",
    ),
    "standard-2025-oct-planned-quantity": (
        "2025年10月的计划产量是多少？",
        "2025年10月",
        "计划产量",
    ),
    "standard-2025-dec-production-quantity": (
        "2025年12月的实际产量是多少？",
        "2025年12月",
        "实际产量",
    ),
    "standard-2025-dec-planned-quantity": (
        "2025年12月的计划数量是多少？",
        "2025年12月",
        "计划数量",
    ),
    "standard-2026-jan-production-quantity": (
        "2026年1月的完工数量是多少？",
        "2026年1月",
        "完工数量",
    ),
    "standard-2026-jan-planned-quantity": ("2026年1月的计划产量是多少？", "2026年1月", "计划产量"),
    "standard-2026-mar-production-quantity": (
        "2026年3月的生产产量是多少？",
        "2026年3月",
        "生产产量",
    ),
    "standard-2026-mar-planned-quantity": ("2026年3月的计划数量是多少？", "2026年3月", "计划数量"),
    "standard-2026-jul-production-quantity": (
        "2026年7月的实际产量是多少？",
        "2026年7月",
        "实际产量",
    ),
    "standard-2026-jul-planned-quantity": ("2026年7月的计划产量是多少？", "2026年7月", "计划产量"),
    "standard-2026-sep-production-quantity": (
        "2026年9月的完工数量是多少？",
        "2026年9月",
        "完工数量",
    ),
    "standard-2026-sep-planned-quantity": ("2026年9月的计划数量是多少？", "2026年9月", "计划数量"),
}
MONTH_CASES.update(
    {
        f"standard-{key}-completion-rate": (f"{month}的{label}是多少？", month, label)
        for key, month, label in (
            ("2025-oct", "2025年10月", "计划达成率"),
            ("2025-dec", "2025年12月", "达成率"),
            ("2026-jan", "2026年1月", "计划达成率"),
            ("2026-mar", "2026年3月", "达成率"),
            ("2026-jul", "2026年7月", "计划达成率"),
            ("2026-sep", "2026年9月", "达成率"),
        )
    }
)
ANOMALY_CASES = {
    "anomaly-no-matching-month": ("2000年1月的不良率是多少？", "2000年1月"),
    "anomaly-zero-denominator": ("1999年1月的不良率是多少？", "1999年1月"),
}
MISSING_COLUMN_ID = "anomaly-source-column-disappeared"
MISSING_COLUMN_TURN = "2026年9月的不良率是多少？"

# Independent source fixtures: never build rows from a case's expected numbers.
NUMERIC_BOUNDARIES: dict[str, tuple[tuple[int, int, str], ...]] = {
    "zero-defects": ((0, 400, "2026-09-05T09:00:00Z"),),
    "all-defective": ((400, 400, "2026-09-05T09:00:00Z"),),
    "tiny-rate": ((1, 100000000, "2026-09-05T09:00:00Z"),),
    "large-volume": ((1000000000000, 4000000000000, "2026-09-05T09:00:00Z"),),
    "weighted-batches": (
        (1, 10, "2026-09-05T09:00:00Z"),
        (9, 990, "2026-09-06T09:00:00Z"),
    ),
    "same-timestamp-batches": (
        (7, 100, "2026-09-05T09:00:00Z"),
        (3, 100, "2026-09-05T09:00:00Z"),
    ),
    "exclusive-month-end": (
        (4, 100, "2026-09-01T00:00:00Z"),
        (1, 100, "2026-09-30T23:59:59Z"),
        (900, 1000, "2026-10-01T00:00:00Z"),
    ),
}


def pinned_numeric_boundary(case: EvaluationCase) -> tuple[tuple[int, int, str], ...] | None:
    key = case.id.removeprefix("anomaly-numeric-")
    if (
        case.id.startswith("anomaly-numeric-")
        and case.category == "anomaly"
        and case.turns == ("2026年9月的不良率是多少？",)
    ):
        return NUMERIC_BOUNDARIES.get(key)
    return None


def pinned_anomaly(case: EvaluationCase) -> str | None:
    spec = ANOMALY_CASES.get(case.id)
    if spec is None or case.category != "anomaly" or case.turns != (spec[0],):
        return None
    return spec[1]


def pinned_missing_column(case: EvaluationCase) -> bool:
    return (
        case.id == MISSING_COLUMN_ID
        and case.category == "anomaly"
        and case.turns == (MISSING_COLUMN_TURN,)
    )


def verify_missing_column_failure(view: AnalysisRunViewResponse) -> bool:
    if view.run.status != "failed" or not view.run.error_code:
        return False
    replies = [item for item in view.messages if item.role == "assistant"]
    return (
        bool(replies)
        and "没有产生可用结论" in replies[-1].content
        and "answer_claims" not in replies[-1].context_patch
        and not any(item.artifact_type == "query_result" for item in view.artifacts)
        and not view.evidence
        and not view.validations
    )


def verify_null_metric(view: AnalysisRunViewResponse, metric_key: str = "defect_rate") -> bool:
    queries = [item for item in view.artifacts if item.artifact_type == "query_result"]
    if len(queries) != 1:
        return False
    summary = queries[0].summary
    replies = [item for item in view.messages if item.role == "assistant"]
    if not replies:
        return False
    reply = replies[-1]
    return (
        summary.get("columns") == [metric_key]
        and summary.get("rows") == [[None]]
        and summary.get("truncated") is False
        and "无法计算" in reply.content
        and "不能把它当作 0" in reply.content
        and "仅凭当前结果还不能确定具体原因" in reply.content
        and "answer_claims" not in reply.context_patch
    )


def pinned_month(case: EvaluationCase) -> str | None:
    spec = MONTH_CASES.get(case.id)
    if spec is None or case.category != "standard" or case.turns != (spec[0],):
        return None
    return spec[1]


def pinned_metric(case: EvaluationCase) -> str | None:
    spec = MONTH_CASES.get(case.id)
    if spec is None or case.category != "standard" or case.turns != (spec[0],):
        return None
    return spec[2]


def owned_schema_name(token: uuid.UUID) -> str:
    name = f"eval_{token.hex}"
    if re.fullmatch(r"eval_[0-9a-f]{32}", name) is None:
        raise ValueError("evaluation.invalid_fixture_schema")
    return name


def pinned_multiturn(case: EvaluationCase) -> bool:
    spec = MULTITURN_CASES.get(case.id)
    return spec is not None and case.category == "multi_turn" and case.turns == spec.turns


def verify_monthly_result(
    view: AnalysisRunViewResponse,
    metric_key: str = "defect_rate",
    months: tuple[str, ...] = ("2026-07", "2026-08", "2026-09"),
) -> bool:
    """Fixed fixture oracle, not values generated from model output or expectations."""
    oracles = {
        "defect_rate": ("inspection_time", ("1.75", "2.75", "3.00")),
        "inspected_quantity": ("inspection_time", ("400", "400", "400")),
        "production_quantity": ("production_time", ("972", "961", "947")),
        "plan_completion_rate": ("production_time", ("97.2", "96.1", "94.7")),
        "qualified_quantity": ("inspection_time", ("360", "380", "480")),
        "first_pass_yield": ("inspection_time", ("85", "90", "90")),
        "scrap_rate": ("inspection_time", ("2", "1", "2")),
        "rework_rate": ("inspection_time", ("3", "2", "1")),
        "inspection_pass_rate": ("inspection_time", ("90", "95", "96")),
        "defect_ppm": ("inspection_time", ("100000", "50000", "40000")),
    }
    oracle = oracles.get(metric_key)
    if oracle is None:
        return False
    queries = [item for item in view.artifacts if item.artifact_type == "query_result"]
    if len(queries) != 1:
        return False
    summary = queries[0].summary
    columns, rows = summary.get("columns"), summary.get("rows")
    if (
        columns != [oracle[0], metric_key]
        or not isinstance(rows, list)
        or len(rows) != len(months)
        or summary.get("truncated") is not False
    ):
        return False
    expected = dict(
        zip(
            ("2026-07", "2026-08", "2026-09"),
            (Decimal(value) for value in oracle[1]),
            strict=True,
        )
    )
    if (
        not months
        or len(set(months)) != len(months)
        or any(month not in expected for month in months)
    ):
        return False
    expected = {month: expected[month] for month in months}
    actual: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            return False
        try:
            timestamp = datetime.fromisoformat(str(row[0]))
            if timestamp.tzinfo is None:
                return False
            timestamp = timestamp.astimezone(UTC)
            if (
                timestamp.day,
                timestamp.hour,
                timestamp.minute,
                timestamp.second,
                timestamp.microsecond,
            ) != (1, 0, 0, 0, 0):
                return False
            month = timestamp.strftime("%Y-%m")
            if month in actual:
                return False
            number = Decimal(str(row[1]))
            if not number.is_finite():
                return False
            actual[month] = number
        except (ValueError, ArithmeticError):
            return False
    return actual == expected


def verify_explanation(view: AnalysisRunViewResponse, source: AnalysisRunViewResponse) -> bool:
    references = [
        item for item in view.evidence if item.evidence_type == "verified_result_reference"
    ]
    replies = [item for item in view.messages if item.role == "assistant"]
    if len(references) != 1 or not replies:
        return False
    reference = references[0].reference
    source_artifact = next(
        (
            item
            for item in source.artifacts
            if str(item.id) == reference.get("source_artifact_id")
            and item.artifact_type in {"query_result", "analysis_summary", "chart_spec"}
        ),
        None,
    )
    source_evidence = next(
        (
            item
            for item in source.evidence
            if str(item.id) == reference.get("source_evidence_id")
            and source_artifact is not None
            and item.artifact_id == source_artifact.id
        ),
        None,
    )
    return (
        source_artifact is not None
        and source_evidence is not None
        and any(item.outcome == "passed" for item in source.validations)
        and view.run.status == "completed"
        and view.run.context.get("follow_up_relation") == "explain"
        and view.run.context.get("previous_run_id") == str(source.run.id)
        and [item.tool_name for item in view.tool_calls] == ["analysis.describe"]
        and not any(item.artifact_type == "query_result" for item in view.artifacts)
        and reference.get("source_run_id") == str(source.run.id)
        and any(
            item.validation_type == "verified_result_reference" and item.outcome == "passed"
            for item in view.validations
        )
        and "仅凭汇总结果不能可靠判断原因" in replies[-1].content
        and "answer_claims" not in replies[-1].context_patch
    )


def verify_social_interruption(view: AnalysisRunViewResponse) -> bool:
    replies = [item for item in view.messages if item.role == "assistant"]
    return (
        view.run.status == "completed"
        and view.run.context.get("follow_up_relation") == "continue"
        and [item.tool_name for item in view.tool_calls] == ["system.small_talk"]
        and not any(item.artifact_type == "query_result" for item in view.artifacts)
        and not view.evidence
        and bool(replies)
        and "你好" in replies[-1].content
    )


class _ConversationSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        spec = MULTITURN_CASES[self.case.id]
        conversation = create_conversation(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisConversationRequest(message=self.case.turns[0]),
        )
        run_ids: list[uuid.UUID] = []
        previous_view: AnalysisRunViewResponse | None = None
        current_metric = spec.metric_key
        current_range = "最近三个月"
        months: tuple[str, ...] = ("2026-07", "2026-08", "2026-09")
        for index, phase in enumerate(spec.phases):
            output: dict[str, object] | None = None
            if phase == "trend":
                output = {
                    "task_type": "trend",
                    "goal": self.case.turns[0],
                    "metrics": [spec.metric_name],
                    "dimensions": ["月份"],
                    "time_range": "最近三个月",
                    "output": ["time_series"],
                    "confidence": 0.99,
                }
            elif phase == "refine":
                output = {
                    "mode": "patch",
                    "patch": {"dimensions": ["月份"], "output": ["time_series"]},
                }
            elif phase in {"september", "august", "recent"}:
                current_range = {
                    "september": "2026年9月",
                    "august": "2026年8月",
                    "recent": "最近三个月",
                }[phase]
                months = {
                    "september": ("2026-09",),
                    "august": ("2026-08",),
                    "recent": ("2026-07", "2026-08", "2026-09"),
                }[phase]
                output = {"mode": "patch", "patch": {"time_range": current_range}}
            elif phase == "switch_metric":
                current_metric = "inspected_quantity"
                output = {"mode": "patch", "patch": {"metrics": ["检验数量"]}}
            if index:
                send_conversation_message(
                    self.db,
                    workspace_id=self.workspace.id,
                    conversation_id=conversation.id,
                    actor_user_id=self.user.id,
                    idempotency_key=f"{self.case.id}:followup:{index}",
                    payload=SendAnalysisConversationMessageRequest(message=self.case.turns[index]),
                )
            run = self.db.scalar(
                select(AnalysisRun)
                .join(AnalysisTurn, AnalysisTurn.analysis_run_id == AnalysisRun.id)
                .where(
                    AnalysisRun.conversation_id == conversation.id,
                )
                .order_by(AnalysisTurn.sequence.desc())
            )
            if run is None or run.id in run_ids:
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            # Freeze only the fixture clock; relative ranges must remain reproducible.
            run.created_at = datetime(2026, 9, 27, index, tzinfo=UTC)
            self.db.commit()
            run_ids.append(run.id)
            responses = (
                [
                    GatewayResponse(
                        f"offline-conversation-{index}",
                        "fake",
                        json.dumps(output, ensure_ascii=False),
                        None,
                        (),
                        "stop",
                        GatewayUsage(20, 10, 30),
                    )
                ]
                if output is not None
                else []
            )
            gateway = FakeGateway(responses)
            run_analysis(self.db, run_id=run.id, gateway=gateway)
            view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
            if view.run.status != "completed":
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            query_phase = phase not in {"social", "explain"}
            if query_phase and not verify_monthly_result(view, current_metric, months):
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            if (
                query_phase
                and len(months) == 1
                and (
                    any(
                        item.artifact_type in {"analysis_summary", "chart_spec"}
                        for item in view.artifacts
                    )
                    or any(
                        item.tool_name in {"analysis.describe", "visualization.compose"}
                        for item in view.tool_calls
                    )
                )
            ):
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            if query_phase:
                intent = view.run.context.get("intent")
                binding = view.run.context.get("binding")
                if (
                    not isinstance(intent, dict)
                    or intent.get("time_range") != current_range
                    or not isinstance(binding, dict)
                    or binding.get("metric_keys") != [current_metric]
                ):
                    return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            if phase == "social" and not verify_social_interruption(view):
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            if phase == "explain" and (
                previous_view is None or not verify_explanation(view, previous_view)
            ):
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            synchronize_conversation_after_run(self.db, run_id=run.id)
            self.db.commit()
            if query_phase:
                previous_view = view
        intent = view.run.context.get("intent")
        if not isinstance(intent, dict) or intent.get("time_range") != current_range:
            return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
        return OfflineCaseExecution(observe_completed_run(view), tuple(run_ids))


def _seed(
    db: Session,
    *,
    source_schema: str = "public",
    production_mapping: bool = False,
    extra_mappings: tuple[tuple[str, str, str, str], ...] = (),
) -> tuple[User, Workspace]:
    user = User(email="evaluation@example.test", display_name="Evaluator", password_hash="unused")
    workspace = Workspace(name="Synthetic PG Evaluation", slug=f"eval-{uuid.uuid4().hex}")
    db.add_all([user, workspace])
    db.flush()
    policy = NetworkPolicy(
        workspace_id=workspace.id,
        name="Synthetic fixture only",
        allowed_private_cidrs=["172.16.0.0/12"],
        allowed_ports=[5432],
        created_by_user_id=user.id,
    )
    db.add(policy)
    db.flush()
    source = DataSource(
        workspace_id=workspace.id,
        network_policy_id=policy.id,
        name="Synthetic quality",
        source_type=DataSourceType.POSTGRESQL,
        host="source-evaluation",
        port=5432,
        database_name="factory_demo",
        tls_mode=TlsMode.DISABLE,
        status=DataSourceStatus.READY,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(source)
    db.flush()
    envelope = EnvelopeSecretProvider.from_settings(get_settings()).encrypt(
        {"username": "zhixi_reader", "password": "reader-local-only"},
        secret_aad(workspace.id, source.id),
    )
    db.add(DataSourceSecret(data_source_id=source.id, **asdict(envelope)))
    metadata = PostgreSQLConnector().scan_metadata(
        ConnectionTarget(source.host, source.port, source.database_name, TlsMode.DISABLE),
        ConnectorCredentials("zhixi_reader", "reader-local-only"),
        NetworkPolicyRules.from_strings(
            allowed_private_cidrs=["172.16.0.0/12"],
            allowed_ports=[5432],
        ),
        MetadataScanOptions(schemas=(source_schema,)),
    )
    snapshot = CatalogSnapshot(
        workspace_id=workspace.id,
        data_source_id=source.id,
        version=1,
        status=SnapshotStatus.PUBLISHED,
        database_product="postgresql",
        object_counts=object_counts(metadata),
    )
    db.add(snapshot)
    db.flush()
    replace_snapshot_document(
        db,
        snapshot_id=snapshot.id,
        workspace_id=workspace.id,
        data_source_id=source.id,
        document=metadata,
    )
    source.active_snapshot_id = snapshot.id
    db.flush()
    document = manufacturing_quality_template()
    mappings = [
        ("inspection", "quality_inspections", "defect_quantity", "defect_quantity"),
        ("inspection", "quality_inspections", "inspected_quantity", "inspected_quantity"),
        ("inspection", "quality_inspections", "inspection_time", "inspected_at"),
    ]
    if source_schema == "public" or production_mapping:
        mappings.extend(
            [
                ("production_order", "production_orders", "order_id", "order_no"),
                ("production_order", "production_orders", "planned_quantity", "planned_quantity"),
                (
                    "production_order",
                    "production_orders",
                    "produced_quantity",
                    "completed_quantity",
                ),
                ("production_order", "production_orders", "start_time", "started_at"),
            ]
        )
    mappings.extend(extra_mappings)
    for entity, relation, attribute, physical in mappings:
        column = db.scalar(
            select(CatalogColumn)
            .join(CatalogRelation)
            .where(
                CatalogRelation.snapshot_id == snapshot.id,
                CatalogRelation.name == relation,
                CatalogColumn.name == physical,
            )
        )
        if column is None:
            raise ValueError("evaluation.fixture_column_missing")
        document.mappings.append(
            PhysicalMapping(
                semantic_attribute=f"{entity}.{attribute}",
                snapshot_id=snapshot.id,
                relation_id=column.relation_id,
                column_id=column.id,
                confirmed=True,
                confidence=1,
                reason="Reviewed synthetic fixture mapping",
            )
        )
    model = create_semantic_model(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        name="Synthetic manufacturing quality",
        description=None,
        document=document,
    )
    publish_semantic_model(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        model_id=model.id,
        version=model.version,
    )
    db.commit()
    return user, workspace


class _MonthSession:
    def __init__(
        self,
        db: Session,
        user: User,
        workspace: Workspace,
        case: EvaluationCase,
        month: str | None,
        metric_name: str,
    ) -> None:
        self.db, self.user, self.workspace, self.case, self.month, self.metric_name = (
            db,
            user,
            workspace,
            case,
            month,
            metric_name,
        )

    def execute(self) -> OfflineCaseExecution:
        run = create_run(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisRunRequest(message=self.case.turns[0]),
        )
        gateway = FakeGateway(
            [
                GatewayResponse(
                    "offline-calendar-month",
                    "fake",
                    json.dumps(
                        {
                            "task_type": "metric_query",
                            "goal": self.case.turns[0],
                            "metrics": [self.metric_name],
                            "time_range": self.month,
                            "confidence": 0.99,
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
        # No metric_executor override: compile, SQL gates, database, evidence are real.
        run_analysis(self.db, run_id=run.id, gateway=gateway)
        view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
        production_rows = pinned_production_boundary(self.case)
        if (
            production_rows is not None
            and sum(planned for _, planned in production_rows) == 0
            and not verify_null_metric(view, "plan_completion_rate")
        ):
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        if pinned_missing_column(self.case):
            valid = verify_missing_column_failure(view)
            return OfflineCaseExecution(
                ObservedOutcome(
                    status="failed" if valid else "completed",
                    tool_calls=tuple(item.tool_name for item in view.tool_calls),
                ),
                (run.id,),
            )
        if (
            self.case.category == "anomaly"
            and pinned_numeric_boundary(self.case) is None
            and production_rows is None
            and not verify_null_metric(view)
        ):
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        observation = (
            observe_completed_run(view)
            if view.run.status == "completed"
            else ObservedOutcome(status="failed")
        )
        return OfflineCaseExecution(observation, (run.id,))


@contextmanager
def postgres_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    month = pinned_month(case)
    metric_name = pinned_metric(case)
    anomaly_month = pinned_anomaly(case)
    missing_column = pinned_missing_column(case)
    multi_turn = pinned_multiturn(case)
    numeric_boundary = pinned_numeric_boundary(case)
    production_boundary = pinned_production_boundary(case)
    quality_metric = pinned_quality_metric(case)
    equipment_metric = pinned_equipment_metric(case)
    quality_conversation = multi_turn and case.id.startswith("multiturn-quality-")
    if case.category == "security":
        from packages.evaluation.security_draft_adapter import security_case_factory

        with security_case_factory(case) as security:
            yield security
        return
    if (
        month is None
        and anomaly_month is None
        and not missing_column
        and not multi_turn
        and numeric_boundary is None
        and production_boundary is None
        and quality_metric is None
        and equipment_metric is None
    ):
        with draft_case_factory(case) as fallback:
            yield fallback
        return
    schema = owned_schema_name(uuid.uuid4())
    admin = create_engine(FIXTURE_URL)
    engine = create_engine(FIXTURE_URL, connect_args={"options": f"-csearch_path={schema}"})
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        Base.metadata.create_all(engine)
        if quality_metric is not None or quality_conversation:
            with admin.begin() as connection:
                spec = quality_metric or QualityMetricSpec(
                    "july", "最近三个月", MULTITURN_CASES[case.id].metric_name
                )
                create_quality_fixture(connection, schema, spec, all_months=quality_conversation)
        if equipment_metric is not None:
            with admin.begin() as connection:
                create_equipment_fixture(connection, schema, equipment_metric)
        if (
            (case.id == "anomaly-zero-denominator" and anomaly_month is not None)
            or missing_column
            or numeric_boundary is not None
            or production_boundary is not None
        ):
            # Only this owned synthetic schema is writable; never mutate public source data.
            with admin.begin() as connection:
                connection.execute(
                    text(
                        f'CREATE TABLE "{schema}".quality_inspections '
                        "(defect_quantity bigint, inspected_quantity bigint, "
                        "inspected_at timestamptz)"
                    )
                )
                if numeric_boundary is not None:
                    connection.execute(
                        text(
                            f'INSERT INTO "{schema}".quality_inspections '
                            "VALUES (:defect, :inspected, :at)"
                        ),
                        [
                            {"defect": defect, "inspected": inspected, "at": at}
                            for defect, inspected, at in numeric_boundary
                        ],
                    )
                elif not missing_column:
                    connection.execute(
                        text(
                            f'INSERT INTO "{schema}".quality_inspections VALUES '
                            "(0, 0, '1999-01-01T00:00:00Z')"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            f'INSERT INTO "{schema}".quality_inspections VALUES '
                            "(12, 400, '2026-09-05T09:00:00Z')"
                        )
                    )
                connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO zhixi_reader'))
                connection.execute(
                    text(f'GRANT SELECT ON "{schema}".quality_inspections TO zhixi_reader')
                )
                if production_boundary is not None:
                    create_production_fixture(connection, schema, production_boundary)
        with Session(engine) as db:
            source_schema = (
                schema
                if (
                    case.id == "anomaly-zero-denominator"
                    or missing_column
                    or numeric_boundary is not None
                    or production_boundary is not None
                    or quality_metric is not None
                    or equipment_metric is not None
                    or quality_conversation
                )
                else "public"
            )
            user, workspace = _seed(
                db,
                source_schema=source_schema,
                production_mapping=production_boundary is not None,
                extra_mappings=(
                    EXTRA_QUALITY_MAPPINGS
                    if quality_metric is not None or quality_conversation
                    else EXTRA_EQUIPMENT_MAPPINGS
                    if equipment_metric is not None
                    else ()
                ),
            )
            if missing_column:
                # The published snapshot still references the field; change only this owned fixture.
                with admin.begin() as connection:
                    connection.execute(
                        text(
                            f'ALTER TABLE "{schema}".quality_inspections '
                            "DROP COLUMN defect_quantity"
                        )
                    )
            if equipment_metric is not None:
                yield _MonthSession(db, user, workspace, case, None, equipment_metric.metric_name)
            elif quality_metric is not None:
                yield _MonthSession(
                    db, user, workspace, case, quality_metric.time_range, quality_metric.metric_name
                )
            elif multi_turn:
                yield _ConversationSession(db, user, workspace, case)
            else:
                selected_month = (
                    month
                    or anomaly_month
                    or (
                        "2026年9月"
                        if missing_column
                        or numeric_boundary is not None
                        or production_boundary is not None
                        else None
                    )
                )
                assert selected_month is not None
                yield _MonthSession(
                    db,
                    user,
                    workspace,
                    case,
                    selected_month,
                    "计划达成率"
                    if production_boundary is not None
                    else (
                        metric_name if month is not None and metric_name is not None else "不良率"
                    ),
                )
    finally:
        engine.dispose()
        try:
            if created:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()
