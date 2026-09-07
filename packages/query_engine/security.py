import hashlib
import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class QuerySecurityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class SafetyReport:
    normalized_sql: str
    digest: str
    dependencies: tuple[str, ...]


_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Merge,
)
_DANGEROUS_FUNCTIONS = {
    "pg_sleep",
    "benchmark",
    "sleep",
    "load_file",
    "pg_read_file",
    "pg_ls_dir",
    "dblink",
}
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys"}


def validate_sql(
    sql: str,
    *,
    dialect: str,
    allowed_relations: set[str],
    max_joins: int = 6,
    max_subqueries: int = 8,
) -> SafetyReport:
    if re.search(r"--|/\*|\*/", sql):
        raise QuerySecurityError("query.comments_forbidden", "SQL comments are forbidden")
    if "\x00" in sql or len(sql) > 50_000:
        raise QuerySecurityError("query.invalid_sql", "SQL payload is invalid")
    parse_sql = sql.replace("%s", "?") if dialect == "mysql" else sql
    try:
        statements = [item for item in parse(parse_sql, read=dialect) if item is not None]
    except ParseError as exc:
        raise QuerySecurityError("query.parse_failed", "SQL could not be parsed") from exc
    if len(statements) != 1:
        raise QuerySecurityError("query.multiple_statements", "Exactly one statement is required")
    root = statements[0]
    if not isinstance(root, exp.Query) or isinstance(root, _FORBIDDEN):
        raise QuerySecurityError(
            "query.read_only_required", "Only read-only SELECT queries are allowed"
        )
    if any(isinstance(node, _FORBIDDEN) for node in root.walk()):
        raise QuerySecurityError(
            "query.write_operation", "Write operations are forbidden, including CTEs"
        )
    with_expression = root.args.get("with_")
    if with_expression is not None and bool(with_expression.args.get("recursive")):
        raise QuerySecurityError("query.recursive_cte", "Recursive CTEs are forbidden")
    joins = list(root.find_all(exp.Join))
    if len(joins) > max_joins:
        raise QuerySecurityError("query.too_many_joins", "Query join budget exceeded")
    for join in joins:
        if str(join.args.get("kind") or "").upper() == "CROSS" or (
            join.args.get("on") is None and join.args.get("using") is None
        ):
            raise QuerySecurityError("query.cartesian_join", "Cartesian joins are forbidden")
    if len(list(root.find_all(exp.Subquery))) > max_subqueries:
        raise QuerySecurityError("query.too_many_subqueries", "Query subquery budget exceeded")
    for function in root.find_all(exp.Func):
        if str(function.name).lower() in _DANGEROUS_FUNCTIONS:
            raise QuerySecurityError(
                "query.dangerous_function", "Dangerous SQL function is forbidden"
            )
    dependencies: set[str] = set()
    approved = {item.lower() for item in allowed_relations}
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        if table.name.lower() in cte_names and not table.db:
            continue
        if table.catalog:
            raise QuerySecurityError("query.cross_database", "Cross-database access is forbidden")
        schema = table.db
        if schema.lower() in _SYSTEM_SCHEMAS:
            raise QuerySecurityError("query.system_schema", "System schemas are forbidden")
        qualified = f"{schema}.{table.name}" if schema else table.name
        if qualified.lower() not in approved:
            raise QuerySecurityError(
                "query.object_denied", f"Relation is not approved: {qualified}"
            )
        dependencies.add(qualified)
    if not dependencies:
        raise QuerySecurityError("query.relation_required", "Query must read an approved relation")
    normalized = root.sql(dialect=dialect, pretty=True)
    if dialect == "mysql":
        normalized = normalized.replace("?", "%s")
    return SafetyReport(
        normalized, hashlib.sha256(normalized.encode()).hexdigest(), tuple(sorted(dependencies))
    )
