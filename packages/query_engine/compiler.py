from collections import deque
from dataclasses import dataclass
from typing import Any

from packages.shared_contracts.queries import SemanticQueryRequest
from packages.shared_contracts.semantic_models import SemanticDocument


class QueryCompilationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ResolvedAttribute:
    semantic_attribute: str
    schema: str
    relation: str
    column: str


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: tuple[object, ...]
    relations: frozenset[str]


def _quote(value: str, dialect: str) -> str:
    marker = "`" if dialect == "mysql" else '"'
    return marker + value.replace(marker, marker * 2) + marker


def _date_bucket(expression: str, grain: str, dialect: str) -> str:
    if dialect == "postgres":
        return f"DATE_TRUNC('{grain}', {expression})"
    formats = {
        "hour": "%Y-%m-%d %H:00:00",
        "day": "%Y-%m-%d",
        "week": "%x-%v",
        "month": "%Y-%m-01",
        "quarter": "%Y-Q%q",
        "year": "%Y-01-01",
    }
    if grain == "quarter":
        return f"CONCAT(YEAR({expression}), '-Q', QUARTER({expression}))"
    return f"DATE_FORMAT({expression}, '{formats[grain]}')"


def compile_semantic_query(
    request: SemanticQueryRequest,
    document: SemanticDocument,
    mappings: dict[str, ResolvedAttribute],
    *,
    dialect: str,
) -> CompiledQuery:
    metrics = {item.key: item for item in document.metrics}
    dimensions = {item.key: item for item in document.dimensions}
    entities = {item.key: item for item in document.entities}
    selected_metrics = []
    for key in request.metrics:
        metric = metrics.get(key)
        if metric is None:
            raise QueryCompilationError("query.metric_not_found", f"Unknown metric: {key}")
        selected_metrics.append(metric)
    selected_dimensions = []
    for key in request.dimensions:
        dimension = dimensions.get(key)
        if dimension is None:
            raise QueryCompilationError("query.dimension_not_found", f"Unknown dimension: {key}")
        selected_dimensions.append(dimension)
    for item in request.filters:
        if item.dimension not in dimensions:
            raise QueryCompilationError(
                "query.dimension_not_found", f"Unknown filter dimension: {item.dimension}"
            )
    if request.time_grain:
        temporal = [item for item in selected_dimensions if item.dimension_type == "temporal"]
        if len(temporal) != 1:
            raise QueryCompilationError(
                "query.temporal_dimension_required",
                "Time grain requires exactly one temporal dimension",
            )
    selected_dimension_keys = set(request.dimensions)
    for metric in selected_metrics:
        unsupported = selected_dimension_keys - set(metric.supported_dimensions)
        if unsupported:
            raise QueryCompilationError(
                "query.dimension_unsupported",
                "Metric "
                + metric.key
                + " does not support dimensions: "
                + ", ".join(sorted(unsupported)),
            )
    metric_entities = {
        reference.split(".", 1)[0]
        for metric in selected_metrics
        for reference in (
            metric.formula.attribute,
            metric.formula.numerator,
            metric.formula.denominator,
        )
        if reference is not None
    }
    if len(metric_entities) > 1:
        relationships_by_pair = {
            frozenset(
                {
                    relationship.from_attribute.split(".", 1)[0],
                    relationship.to_attribute.split(".", 1)[0],
                }
            ): relationship
            for relationship in document.relationships
        }
        for left in metric_entities:
            for right in metric_entities:
                if left >= right:
                    continue
                relationship = relationships_by_pair.get(frozenset({left, right}))
                if relationship is None or relationship.cardinality != "one_to_one":
                    raise QueryCompilationError(
                        "query.fanout_unsafe",
                        "Metrics from different grains require governed pre-aggregation",
                    )
    required_refs: set[str] = set()
    for metric in selected_metrics:
        formula = metric.formula
        required_refs.update(
            item for item in (formula.attribute, formula.numerator, formula.denominator) if item
        )
    for dimension in selected_dimensions:
        required_refs.add(f"{dimension.entity_key}.{dimension.attribute_key}")
    for item in request.filters:
        dimension = dimensions[item.dimension]
        required_refs.add(f"{dimension.entity_key}.{dimension.attribute_key}")
    missing = sorted(item for item in required_refs if item not in mappings)
    if missing:
        raise QueryCompilationError(
            "query.mapping_incomplete", f"Missing confirmed mappings: {', '.join(missing)}"
        )

    required_entities = {item.split(".", 1)[0] for item in required_refs}
    graph: dict[str, list[tuple[str, Any]]] = {key: [] for key in entities}
    for relationship in document.relationships:
        left, right = (
            relationship.from_attribute.split(".", 1)[0],
            relationship.to_attribute.split(".", 1)[0],
        )
        graph[left].append((right, relationship))
        graph[right].append((left, relationship))
    root = next(iter(sorted(required_entities)))
    parent: dict[str, tuple[str, Any]] = {}
    queue = deque([root])
    seen = {root}
    while queue:
        current = queue.popleft()
        for neighbor, relationship in graph[current]:
            if neighbor not in seen:
                seen.add(neighbor)
                parent[neighbor] = (current, relationship)
                queue.append(neighbor)
    if not required_entities.issubset(seen):
        raise QueryCompilationError(
            "query.join_path_missing", "Selected fields do not have a governed relationship path"
        )
    included = set(required_entities)
    for entity in list(required_entities):
        cursor = entity
        while cursor != root:
            cursor = parent[cursor][0]
            included.add(cursor)
    relation_for_entity: dict[str, tuple[str, str]] = {}
    for ref, mapping in mappings.items():
        entity = ref.split(".", 1)[0]
        value = (mapping.schema, mapping.relation)
        previous = relation_for_entity.setdefault(entity, value)
        if previous != value:
            raise QueryCompilationError(
                "query.entity_spans_relations", f"Entity {entity} spans multiple physical relations"
            )
    aliases = {entity: f"t{index}" for index, entity in enumerate(sorted(included))}

    def column(ref: str) -> str:
        mapping = mappings[ref]
        entity = ref.split(".", 1)[0]
        return f"{aliases[entity]}.{_quote(mapping.column, dialect)}"

    def table(entity: str) -> str:
        schema, relation = relation_for_entity[entity]
        return f"{_quote(schema, dialect)}.{_quote(relation, dialect)} {aliases[entity]}"

    from_sql = table(root)
    connected = {root}
    while not included.issubset(connected):
        progressed = False
        for entity in sorted(included - connected):
            if entity not in parent:
                continue
            ancestor, relationship = parent[entity]
            if ancestor not in connected:
                continue
            left, right = relationship.from_attribute, relationship.to_attribute
            from_sql += f" JOIN {table(entity)} ON {column(left)} = {column(right)}"
            connected.add(entity)
            progressed = True
        if not progressed:
            raise QueryCompilationError("query.join_path_missing", "Could not construct join path")

    select_items: list[str] = []
    group_items: list[str] = []
    for dimension in selected_dimensions:
        expression = column(f"{dimension.entity_key}.{dimension.attribute_key}")
        if request.time_grain and dimension.dimension_type == "temporal":
            expression = _date_bucket(expression, request.time_grain, dialect)
        select_items.append(f"{expression} AS {_quote(dimension.key, dialect)}")
        group_items.append(expression)
    for metric in selected_metrics:
        formula = metric.formula
        if formula.type == "count":
            expression = f"COUNT({column(formula.attribute)})" if formula.attribute else "COUNT(*)"
        elif formula.type == "count_distinct":
            expression = f"COUNT(DISTINCT {column(formula.attribute or '')})"
        elif formula.type == "average":
            expression = f"AVG({column(formula.attribute or '')})"
        elif formula.type in {"sum", "min", "max"}:
            expression = f"{formula.type.upper()}({column(formula.attribute or '')})"
        else:
            numerator, denominator = (
                column(formula.numerator or ""),
                column(formula.denominator or ""),
            )
            expression = f"(SUM({numerator}) * {formula.scale}) / NULLIF(SUM({denominator}), 0)"
        select_items.append(f"{expression} AS {_quote(metric.key, dialect)}")
    parameters: list[object] = []
    predicates: list[str] = []
    operators = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for item in request.filters:
        dimension = dimensions[item.dimension]
        expression = column(f"{dimension.entity_key}.{dimension.attribute_key}")
        values = item.value if isinstance(item.value, list) else [item.value]
        if item.operator in operators:
            predicates.append(f"{expression} {operators[item.operator]} %s")
        elif item.operator == "between":
            predicates.append(f"{expression} BETWEEN %s AND %s")
        else:
            negation = " NOT" if item.operator == "not_in" else ""
            predicates.append(f"{expression}{negation} IN ({', '.join('%s' for _ in values)})")
        parameters.extend(values)
    sql = f"SELECT {', '.join(select_items)} FROM {from_sql}"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if group_items:
        sql += " GROUP BY " + ", ".join(group_items)
    if request.comparison == "previous_period":
        temporal_keys = [
            item.key for item in selected_dimensions if item.dimension_type == "temporal"
        ]
        if len(temporal_keys) != 1:
            raise QueryCompilationError(
                "query.temporal_dimension_required",
                "Previous-period comparison requires exactly one temporal dimension",
            )
        time_key = _quote(temporal_keys[0], dialect)
        comparison_items = ["aggregated.*"]
        for metric_key in request.metrics:
            metric_alias = _quote(metric_key, dialect)
            previous_alias = _quote(f"{metric_key}_previous", dialect)
            change_alias = _quote(f"{metric_key}_change_percent", dialect)
            lag = f"LAG({metric_alias}) OVER (ORDER BY {time_key})"
            comparison_items.append(f"{lag} AS {previous_alias}")
            comparison_items.append(
                f"(({metric_alias} - {lag}) * 100.0) / NULLIF({lag}, 0) AS {change_alias}"
            )
        sql = f"WITH aggregated AS ({sql}) SELECT {', '.join(comparison_items)} FROM aggregated"
    allowed_sort = set(request.metrics) | set(request.dimensions)
    if request.sort:
        for sort_item in request.sort:
            if sort_item.field not in allowed_sort:
                raise QueryCompilationError(
                    "query.sort_not_selected", f"Sort field is not selected: {sort_item.field}"
                )
        sql += " ORDER BY " + ", ".join(
            f"{_quote(sort_item.field, dialect)} {sort_item.direction.upper()}"
            for sort_item in request.sort
        )
    elif request.metrics:
        sql += f" ORDER BY {_quote(request.metrics[0], dialect)} DESC"
    sql += f" LIMIT {request.limit + 1}"
    relations = frozenset(
        f"{schema}.{relation}" for schema, relation in relation_for_entity.values()
    )
    return CompiledQuery(sql, tuple(parameters), relations)
