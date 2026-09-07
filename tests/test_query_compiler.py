import uuid

import pytest

from packages.query_engine.compiler import (
    QueryCompilationError,
    ResolvedAttribute,
    compile_semantic_query,
)
from packages.query_engine.security import validate_sql
from packages.shared_contracts.queries import SemanticQueryRequest
from packages.shared_contracts.semantic_models import SemanticDocument


def _document() -> SemanticDocument:
    return SemanticDocument.model_validate(
        {
            "entities": [
                {
                    "key": "orders",
                    "name": "工单",
                    "attributes": [
                        {"key": "id", "name": "编号", "data_type": "string", "is_identifier": True},
                        {"key": "started", "name": "时间", "data_type": "datetime"},
                        {"key": "amount", "name": "产量", "data_type": "number"},
                    ],
                },
                {
                    "key": "quality",
                    "name": "质检",
                    "attributes": [
                        {"key": "order_id", "name": "工单", "data_type": "string"},
                        {"key": "good", "name": "合格", "data_type": "number"},
                        {"key": "total", "name": "检验", "data_type": "number"},
                    ],
                },
            ],
            "relationships": [
                {
                    "key": "quality_order",
                    "name": "质检工单",
                    "from_attribute": "quality.order_id",
                    "to_attribute": "orders.id",
                    "cardinality": "many_to_one",
                }
            ],
            "dimensions": [
                {
                    "key": "production_time",
                    "name": "生产时间",
                    "entity_key": "orders",
                    "attribute_key": "started",
                    "dimension_type": "temporal",
                }
            ],
            "metrics": [
                {
                    "key": "output",
                    "name": "产量",
                    "description": "总产量",
                    "formula": {"type": "sum", "attribute": "orders.amount"},
                    "unit": "件",
                    "supported_dimensions": ["production_time"],
                },
                {
                    "key": "pass_rate",
                    "name": "合格率",
                    "description": "汇总后相除",
                    "formula": {
                        "type": "ratio_of_sums",
                        "numerator": "quality.good",
                        "denominator": "quality.total",
                        "scale": 100,
                    },
                    "unit": "%",
                    "supported_dimensions": ["production_time"],
                },
            ],
            "mappings": [],
        }
    )


def _mappings() -> dict[str, ResolvedAttribute]:
    values = {
        "orders.id": ("public", "orders", "id"),
        "orders.started": ("public", "orders", "started_at"),
        "orders.amount": ("public", "orders", "amount"),
        "quality.order_id": ("public", "inspections", "order_id"),
        "quality.good": ("public", "inspections", "good_count"),
        "quality.total": ("public", "inspections", "total_count"),
    }
    return {key: ResolvedAttribute(key, *value) for key, value in values.items()}


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_compiles_joined_trend_ratio_and_parameters(dialect: str) -> None:
    request = SemanticQueryRequest.model_validate(
        {
            "semantic_model_id": str(uuid.uuid4()),
            "metrics": ["pass_rate"],
            "dimensions": ["production_time"],
            "time_grain": "month",
            "filters": [
                {
                    "dimension": "production_time",
                    "operator": "between",
                    "value": ["2026-01-01", "2026-12-31"],
                }
            ],
            "sort": [{"field": "production_time", "direction": "asc"}],
            "limit": 100,
        }
    )
    compiled = compile_semantic_query(request, _document(), _mappings(), dialect=dialect)
    assert " JOIN " in compiled.sql
    assert "NULLIF(SUM(" in compiled.sql
    assert compiled.parameters == ("2026-01-01", "2026-12-31")
    assert compiled.sql.endswith("LIMIT 101")
    report = validate_sql(compiled.sql, dialect=dialect, allowed_relations=set(compiled.relations))
    assert set(report.dependencies) == {"public.inspections", "public.orders"}


def test_rejects_missing_physical_mapping() -> None:
    request = SemanticQueryRequest(semantic_model_id=uuid.uuid4(), metrics=["output"])
    with pytest.raises(QueryCompilationError) as caught:
        compile_semantic_query(request, _document(), {}, dialect="postgres")
    assert caught.value.code == "query.mapping_incomplete"


def test_compiles_previous_period_comparison() -> None:
    request = SemanticQueryRequest(
        semantic_model_id=uuid.uuid4(),
        metrics=["output"],
        dimensions=["production_time"],
        time_grain="month",
        comparison="previous_period",
    )
    compiled = compile_semantic_query(request, _document(), _mappings(), dialect="postgres")
    assert "WITH aggregated AS" in compiled.sql
    assert 'LAG("output")' in compiled.sql
    assert "output_change_percent" in compiled.sql
    validate_sql(compiled.sql, dialect="postgres", allowed_relations=set(compiled.relations))


def test_rejects_cross_grain_metric_fanout() -> None:
    request = SemanticQueryRequest(
        semantic_model_id=uuid.uuid4(),
        metrics=["output", "pass_rate"],
        dimensions=["production_time"],
    )
    with pytest.raises(QueryCompilationError) as caught:
        compile_semantic_query(request, _document(), _mappings(), dialect="postgres")
    assert caught.value.code == "query.fanout_unsafe"
