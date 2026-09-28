"""Network and failure routing for the read-only query executor."""

import ipaddress
from decimal import Decimal

import psycopg
import pytest

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import NetworkPolicyError, NetworkPolicyRules
from packages.query_engine import runtime


def _arguments():
    return (
        ConnectionTarget("source.internal", 5432, "factory", TlsMode.DISABLE),
        ConnectorCredentials("reader", "synthetic-test-only"),
        NetworkPolicyRules.from_strings(allowed_private_cidrs=["10.0.0.0/8"], allowed_ports=[5432]),
    )


def test_network_denial_never_invokes_database(monkeypatch) -> None:
    target, credentials, rules = _arguments()

    def denied(*_args):
        raise NetworkPolicyError("network_policy.denied", "synthetic denial")

    monkeypatch.setattr(runtime, "resolve_host", denied)
    monkeypatch.setattr(runtime, "_execute_postgres", lambda *_args: pytest.fail("connected"))
    with pytest.raises(ConnectorError) as caught:
        runtime.execute_read_only(
            DataSourceType.POSTGRESQL, target, credentials, rules, "SELECT 1", (), row_limit=1
        )
    assert caught.value.code == "network_policy.denied"


@pytest.mark.parametrize("database", [DataSourceType.POSTGRESQL, DataSourceType.MYSQL])
def test_authorized_address_and_limits_reach_only_selected_dialect(monkeypatch, database) -> None:
    target, credentials, rules = _arguments()
    address = ipaddress.ip_address("10.1.2.3")
    result = runtime.QueryResult(("value",), ((1,),), False)
    calls = []
    monkeypatch.setattr(runtime, "resolve_host", lambda _host: (address,))
    monkeypatch.setattr(runtime, "authorize_destination", lambda *_args: (address,))

    def selected(*args):
        calls.append(args)
        return result

    selected_name = (
        "_execute_postgres" if database is DataSourceType.POSTGRESQL else "_execute_mysql"
    )
    other_name = "_execute_mysql" if database is DataSourceType.POSTGRESQL else "_execute_postgres"
    monkeypatch.setattr(runtime, selected_name, selected)
    monkeypatch.setattr(runtime, other_name, lambda *_args: pytest.fail("wrong dialect"))
    assert (
        runtime.execute_read_only(
            database,
            target,
            credentials,
            rules,
            "SELECT %s",
            (1,),
            row_limit=2,
            statement_timeout_seconds=3,
        )
        == result
    )
    assert len(calls) == 1
    assert calls[0][3] == (address,) and calls[0][4] == address
    assert calls[0][5:] == ("SELECT %s", (1,), 2, 3)


@pytest.mark.parametrize(
    "failure,code,retryable",
    [
        (TimeoutError("socket timeout"), "query.timeout", True),
        (psycopg.OperationalError("connection refused"), "query.execution_failed", False),
    ],
)
def test_connection_failures_are_classified_after_all_authorized_addresses(
    monkeypatch, failure, code, retryable
) -> None:
    target, credentials, rules = _arguments()
    addresses = (ipaddress.ip_address("10.1.2.3"), ipaddress.ip_address("10.1.2.4"))
    calls = []
    monkeypatch.setattr(runtime, "resolve_host", lambda _host: addresses)
    monkeypatch.setattr(runtime, "authorize_destination", lambda *_args: addresses)

    def failed(*args):
        calls.append(args[4])
        raise failure

    monkeypatch.setattr(runtime, "_execute_postgres", failed)
    with pytest.raises(ConnectorError) as caught:
        runtime.execute_read_only(
            DataSourceType.POSTGRESQL, target, credentials, rules, "SELECT 1", (), row_limit=1
        )
    assert caught.value.code == code and caught.value.retryable is retryable
    assert calls == list(addresses)


def test_query_value_conversion_keeps_json_safe_scalars() -> None:
    assert runtime._json_value(None) is None
    assert runtime._json_value(True) is True
    assert runtime._json_value(Decimal("2.5")) == 2.5
    assert runtime._json_value(ipaddress.ip_address("10.0.0.1")) == "10.0.0.1"
