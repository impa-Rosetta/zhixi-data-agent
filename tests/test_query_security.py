import pytest

from packages.query_engine.security import QuerySecurityError, validate_sql

ALLOWED = {"public.orders", "public.inspections"}


def test_accepts_governed_parameterized_select() -> None:
    report = validate_sql(
        'SELECT "status", SUM("amount") FROM "public"."orders" '
        'WHERE "created_at" >= %s GROUP BY "status" LIMIT 101',
        dialect="postgres",
        allowed_relations=ALLOWED,
    )
    assert report.dependencies == ("public.orders",)
    assert len(report.digest) == 64


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT * FROM public.orders; DELETE FROM public.orders", "query.multiple_statements"),
        ("SELECT * FROM public.orders -- bypass", "query.comments_forbidden"),
        (
            "WITH changed AS (DELETE FROM public.orders RETURNING *) SELECT * FROM changed",
            "query.write_operation",
        ),
        ("SELECT * FROM information_schema.tables", "query.system_schema"),
        ("SELECT pg_sleep(10) FROM public.orders", "query.dangerous_function"),
        ("SELECT * FROM public.orders CROSS JOIN public.inspections", "query.cartesian_join"),
        ("SELECT * FROM public.orders JOIN public.inspections", "query.cartesian_join"),
        ("SELECT * FROM public.unknown", "query.object_denied"),
        ("UPDATE public.orders SET amount = 0", "query.read_only_required"),
    ],
)
def test_rejects_attack_matrix(sql: str, code: str) -> None:
    with pytest.raises(QuerySecurityError) as caught:
        validate_sql(sql, dialect="postgres", allowed_relations=ALLOWED)
    assert caught.value.code == code


def test_mysql_dialect_bypass_is_rejected() -> None:
    with pytest.raises(QuerySecurityError) as caught:
        validate_sql(
            "SELECT SLEEP(10) FROM `factory`.`orders`",
            dialect="mysql",
            allowed_relations={"factory.orders"},
        )
    assert caught.value.code == "query.dangerous_function"
