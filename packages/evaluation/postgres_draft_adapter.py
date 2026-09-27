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
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
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
from packages.evaluation.observation import observe_completed_run
from packages.evaluation.runner import OfflineCaseExecution, OfflineCaseSession
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

ADAPTER_VERSION = "draft-postgres-conversation-v1"
MULTITURN_ID = "multiturn-trend-then-monthly"
MULTITURN_TURNS = ("最近三个月不良率趋势", "按月份展开")
FIXTURE_URL = (
    "postgresql+psycopg://source_admin:source-admin-local-only@source-evaluation:5432/factory_demo"
)
MONTH_CASES = {
    "standard-july-defect-rate": ("2026年7月的不良率是多少？", "2026年7月"),
    "standard-august-defect-rate": ("2026年8月的不良率是多少？", "2026年8月"),
    "standard-september-defect-rate": ("2026年9月的不良率是多少？", "2026年9月"),
}


def pinned_month(case: EvaluationCase) -> str | None:
    spec = MONTH_CASES.get(case.id)
    if spec is None or case.category != "standard" or case.turns != (spec[0],):
        return None
    return spec[1]


def owned_schema_name(token: uuid.UUID) -> str:
    name = f"eval_{token.hex}"
    if re.fullmatch(r"eval_[0-9a-f]{32}", name) is None:
        raise ValueError("evaluation.invalid_fixture_schema")
    return name


def pinned_multiturn(case: EvaluationCase) -> bool:
    return (
        case.id == MULTITURN_ID and case.category == "multi_turn" and case.turns == MULTITURN_TURNS
    )


def verify_monthly_result(view: AnalysisRunViewResponse) -> bool:
    """Fixed fixture oracle, not values generated from model output or expectations."""
    queries = [item for item in view.artifacts if item.artifact_type == "query_result"]
    if len(queries) != 1:
        return False
    summary = queries[0].summary
    columns, rows = summary.get("columns"), summary.get("rows")
    if (
        columns != ["inspection_time", "defect_rate"]
        or not isinstance(rows, list)
        or len(rows) != 3
        or summary.get("truncated") is not False
    ):
        return False
    expected = (
        ("2026-07", Decimal("1.75")),
        ("2026-08", Decimal("2.75")),
        ("2026-09", Decimal("3.00")),
    )
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
    return actual == dict(expected)


class _ConversationSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        conversation = create_conversation(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisConversationRequest(message=self.case.turns[0]),
        )
        run_ids: list[uuid.UUID] = []
        outputs = (
            {
                "task_type": "trend",
                "goal": self.case.turns[0],
                "metrics": ["不良率"],
                "dimensions": ["月份"],
                "time_range": "最近三个月",
                "output": ["time_series"],
                "confidence": 0.99,
            },
            {"mode": "patch", "patch": {"dimensions": ["月份"], "output": ["time_series"]}},
        )
        for index, output in enumerate(outputs):
            if index:
                send_conversation_message(
                    self.db,
                    workspace_id=self.workspace.id,
                    conversation_id=conversation.id,
                    actor_user_id=self.user.id,
                    idempotency_key=f"{self.case.id}:followup",
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
            gateway = FakeGateway(
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
            )
            run_analysis(self.db, run_id=run.id, gateway=gateway)
            view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
            if view.run.status != "completed" or not verify_monthly_result(view):
                return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
            synchronize_conversation_after_run(self.db, run_id=run.id)
            self.db.commit()
        intent = view.run.context.get("intent")
        if not isinstance(intent, dict) or intent.get("time_range") != "最近三个月":
            return OfflineCaseExecution(ObservedOutcome(status="failed"), tuple(run_ids))
        return OfflineCaseExecution(observe_completed_run(view), tuple(run_ids))


def _seed(db: Session) -> tuple[User, Workspace]:
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
        MetadataScanOptions(schemas=("public",)),
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
    for attribute, physical in (
        ("defect_quantity", "defect_quantity"),
        ("inspected_quantity", "inspected_quantity"),
        ("inspection_time", "inspected_at"),
    ):
        column = db.scalar(
            select(CatalogColumn)
            .join(CatalogRelation)
            .where(
                CatalogRelation.snapshot_id == snapshot.id,
                CatalogRelation.name == "quality_inspections",
                CatalogColumn.name == physical,
            )
        )
        if column is None:
            raise ValueError("evaluation.fixture_column_missing")
        document.mappings.append(
            PhysicalMapping(
                semantic_attribute=f"inspection.{attribute}",
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
        self, db: Session, user: User, workspace: Workspace, case: EvaluationCase, month: str
    ) -> None:
        self.db, self.user, self.workspace, self.case, self.month = (
            db,
            user,
            workspace,
            case,
            month,
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
                            "metrics": ["不良率"],
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
        observation = (
            observe_completed_run(view)
            if view.run.status == "completed"
            else ObservedOutcome(status="failed")
        )
        return OfflineCaseExecution(observation, (run.id,))


@contextmanager
def postgres_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    month = pinned_month(case)
    multi_turn = pinned_multiturn(case)
    if month is None and not multi_turn:
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
        with Session(engine) as db:
            user, workspace = _seed(db)
            if multi_turn:
                yield _ConversationSession(db, user, workspace, case)
            else:
                assert month is not None
                yield _MonthSession(db, user, workspace, case, month)
    finally:
        engine.dispose()
        try:
            if created:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()
