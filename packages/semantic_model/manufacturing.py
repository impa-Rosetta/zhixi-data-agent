from packages.shared_contracts.semantic_models import SemanticDocument


def manufacturing_quality_template() -> SemanticDocument:
    entity_specs = {
        "production_order": (
            "生产工单",
            [
                ("order_id", "工单编号", "string", True),
                ("planned_quantity", "计划数量", "number", False),
                ("produced_quantity", "生产数量", "number", False),
                ("start_time", "开始时间", "datetime", False),
            ],
        ),
        "inspection": (
            "质量检验",
            [
                ("inspection_id", "检验编号", "string", True),
                ("order_id", "工单编号", "string", False),
                ("inspected_quantity", "检验数量", "number", False),
                ("qualified_quantity", "合格数量", "number", False),
                ("defect_quantity", "缺陷数量", "number", False),
                ("scrap_quantity", "报废数量", "number", False),
                ("rework_quantity", "返工数量", "number", False),
                ("first_pass_quantity", "一次通过数量", "number", False),
                ("inspection_time", "检验时间", "datetime", False),
            ],
        ),
        "equipment_event": (
            "设备事件",
            [
                ("event_id", "事件编号", "string", True),
                ("equipment_id", "设备编号", "string", False),
                ("runtime_hours", "运行时长", "number", False),
                ("planned_hours", "计划时长", "number", False),
                ("downtime_hours", "停机时长", "number", False),
                ("failure_count", "故障次数", "integer", False),
                ("repair_hours", "维修时长", "number", False),
                ("ideal_output", "理论产量", "number", False),
                ("actual_output", "实际产量", "number", False),
            ],
        ),
    }
    entities = []
    for key, (name, attributes) in entity_specs.items():
        entities.append(
            {
                "key": key,
                "name": name,
                "description": f"{name}主题实体",
                "attributes": [
                    {
                        "key": item[0],
                        "name": item[1],
                        "data_type": item[2],
                        "is_identifier": item[3],
                    }
                    for item in attributes
                ],
            }
        )
    dimensions = [
        {
            "key": "order",
            "name": "工单",
            "entity_key": "production_order",
            "attribute_key": "order_id",
            "dimension_type": "categorical",
            "aliases": ["生产单"],
        },
        {
            "key": "production_time",
            "name": "生产时间",
            "entity_key": "production_order",
            "attribute_key": "start_time",
            "dimension_type": "temporal",
            "aliases": ["日期", "月份"],
        },
        {
            "key": "inspection_time",
            "name": "检验时间",
            "entity_key": "inspection",
            "attribute_key": "inspection_time",
            "dimension_type": "temporal",
            "aliases": ["质检日期"],
        },
        {
            "key": "equipment",
            "name": "设备",
            "entity_key": "equipment_event",
            "attribute_key": "equipment_id",
            "dimension_type": "categorical",
            "aliases": ["机器", "机台"],
        },
    ]
    dims = ["order", "production_time"]
    quality_dims = ["order", "inspection_time"]
    equipment_dims = ["equipment"]
    metric_specs = [
        (
            "planned_quantity",
            "计划产量",
            "sum",
            "production_order.planned_quantity",
            "件",
            dims,
            ["计划数量"],
        ),
        (
            "production_quantity",
            "生产产量",
            "sum",
            "production_order.produced_quantity",
            "件",
            dims,
            ["实际产量", "完工数量"],
        ),
        (
            "inspected_quantity",
            "检验数量",
            "sum",
            "inspection.inspected_quantity",
            "件",
            quality_dims,
            ["质检数量"],
        ),
        (
            "qualified_quantity",
            "合格数量",
            "sum",
            "inspection.qualified_quantity",
            "件",
            quality_dims,
            ["良品数"],
        ),
        (
            "defect_quantity",
            "缺陷数量",
            "sum",
            "inspection.defect_quantity",
            "件",
            quality_dims,
            ["不良数"],
        ),
        (
            "scrap_quantity",
            "报废数量",
            "sum",
            "inspection.scrap_quantity",
            "件",
            quality_dims,
            ["报废数"],
        ),
        (
            "rework_quantity",
            "返工数量",
            "sum",
            "inspection.rework_quantity",
            "件",
            quality_dims,
            ["返修数"],
        ),
        (
            "downtime_hours",
            "停机时长",
            "sum",
            "equipment_event.downtime_hours",
            "小时",
            equipment_dims,
            ["停机小时"],
        ),
        (
            "failure_count",
            "故障次数",
            "sum",
            "equipment_event.failure_count",
            "次",
            equipment_dims,
            ["故障数"],
        ),
        (
            "repair_hours",
            "维修时长",
            "sum",
            "equipment_event.repair_hours",
            "小时",
            equipment_dims,
            ["修复时间"],
        ),
    ]
    ratio_specs = [
        (
            "first_pass_yield",
            "一次通过率",
            "inspection.first_pass_quantity",
            "inspection.inspected_quantity",
            100,
            "%",
            quality_dims,
            ["直通率", "FPY"],
        ),
        (
            "defect_rate",
            "缺陷率",
            "inspection.defect_quantity",
            "inspection.inspected_quantity",
            100,
            "%",
            quality_dims,
            ["不良率"],
        ),
        (
            "scrap_rate",
            "报废率",
            "inspection.scrap_quantity",
            "inspection.inspected_quantity",
            100,
            "%",
            quality_dims,
            [],
        ),
        (
            "rework_rate",
            "返工率",
            "inspection.rework_quantity",
            "inspection.inspected_quantity",
            100,
            "%",
            quality_dims,
            [],
        ),
        (
            "inspection_pass_rate",
            "检验合格率",
            "inspection.qualified_quantity",
            "inspection.inspected_quantity",
            100,
            "%",
            quality_dims,
            ["良率"],
        ),
        (
            "plan_completion_rate",
            "计划达成率",
            "production_order.produced_quantity",
            "production_order.planned_quantity",
            100,
            "%",
            dims,
            ["达成率"],
        ),
        (
            "equipment_availability",
            "设备可用率",
            "equipment_event.runtime_hours",
            "equipment_event.planned_hours",
            100,
            "%",
            equipment_dims,
            ["开动率"],
        ),
        (
            "performance_rate",
            "性能效率",
            "equipment_event.actual_output",
            "equipment_event.ideal_output",
            100,
            "%",
            equipment_dims,
            ["设备性能"],
        ),
        (
            "defect_ppm",
            "百万件缺陷数",
            "inspection.defect_quantity",
            "inspection.inspected_quantity",
            1_000_000,
            "PPM",
            quality_dims,
            ["DPPM"],
        ),
    ]
    metrics: list[dict[str, object]] = [
        {
            "key": key,
            "name": name,
            "description": f"{name}，采用可聚合的求和口径",
            "formula": {"type": kind, "attribute": attr},
            "unit": unit,
            "time_grain": None,
            "supported_dimensions": ds,
            "aliases": aliases,
        }
        for key, name, kind, attr, unit, ds, aliases in metric_specs
    ]
    metrics.extend(
        {
            "key": key,
            "name": name,
            "description": f"{name}，采用先汇总分子分母再相除的口径",
            "formula": {
                "type": "ratio_of_sums",
                "numerator": numerator,
                "denominator": denominator,
                "scale": scale,
            },
            "unit": unit,
            "time_grain": None,
            "supported_dimensions": ds,
            "aliases": aliases,
        }
        for key, name, numerator, denominator, scale, unit, ds, aliases in ratio_specs
    )
    return SemanticDocument.model_validate(
        {
            "entities": entities,
            "relationships": [
                {
                    "key": "order_inspections",
                    "name": "工单检验",
                    "from_attribute": "inspection.order_id",
                    "to_attribute": "production_order.order_id",
                    "cardinality": "many_to_one",
                }
            ],
            "dimensions": dimensions,
            "metrics": metrics,
            "mappings": [],
        }
    )
