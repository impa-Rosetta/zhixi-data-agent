from packages.semantic_model.manufacturing import manufacturing_quality_template
from packages.semantic_model.synthetic import generate_manufacturing_data


def test_manufacturing_template_has_product_metric_contract() -> None:
    document = manufacturing_quality_template()
    assert len(document.entities) == 3
    assert sum(len(item.attributes) for item in document.entities) == 22
    assert len(document.relationships) == 1
    assert len(document.dimensions) == 4
    assert len(document.metrics) == 19
    metric = next(item for item in document.metrics if item.key == "defect_rate")
    assert metric.formula.type == "ratio_of_sums"
    assert metric.formula.numerator == "inspection.defect_quantity"
    assert metric.formula.denominator == "inspection.inspected_quantity"
    assert metric.formula.scale == 100


def test_synthetic_variants_are_deterministic_and_auditable() -> None:
    first = generate_manufacturing_data(seed=42, variant="standard")
    second = generate_manufacturing_data(seed=42, variant="standard")
    assert first == second
    assert first.expected["defect_rate"] > 0
    assert first.anomalies == [
        {
            "table": "inspection",
            "row": 7,
            "metric": "defect_quantity",
            "kind": "seeded_spike",
        }
    ]
    renamed = generate_manufacturing_data(seed=42, variant="renamed")
    assert "mo_no" in renamed.tables["production_order"][0]
    missing = generate_manufacturing_data(seed=42, variant="missing_column")
    assert "first_pass_quantity" not in missing.tables["inspection"][0]
