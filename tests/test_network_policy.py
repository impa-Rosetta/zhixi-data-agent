import ipaddress

import pytest

from packages.platform_core.network_policy import (
    NetworkPolicyError,
    NetworkPolicyRules,
    authorize_destination,
    normalize_host,
    verify_connected_address,
)


@pytest.fixture
def rules() -> NetworkPolicyRules:
    return NetworkPolicyRules.from_strings(
        allowed_private_cidrs=["10.20.0.0/16", "2001:db8:10::/48"],
        allowed_ports=[5432, 3306],
    )


def test_public_and_allowlisted_private_addresses_are_allowed(
    rules: NetworkPolicyRules,
) -> None:
    public = ipaddress.ip_address("8.8.8.8")
    private = ipaddress.ip_address("10.20.1.8")

    assert authorize_destination("db.example.com", 5432, [public], rules) == (public,)
    assert authorize_destination("10.20.1.8", 3306, [private], rules) == (private,)


@pytest.mark.parametrize(
    ("address", "code"),
    [
        ("127.0.0.1", "network_policy.address_denied"),
        ("169.254.169.254", "network_policy.address_denied"),
        ("100.100.100.200", "network_policy.address_denied"),
        ("10.30.1.8", "network_policy.private_address_denied"),
        ("::1", "network_policy.address_denied"),
        ("fd00:ec2::254", "network_policy.address_denied"),
    ],
)
def test_dangerous_or_unapproved_addresses_are_rejected(
    rules: NetworkPolicyRules,
    address: str,
    code: str,
) -> None:
    with pytest.raises(NetworkPolicyError) as raised:
        authorize_destination(address, 5432, [ipaddress.ip_address(address)], rules)

    assert raised.value.code == code


def test_unapproved_port_is_rejected(rules: NetworkPolicyRules) -> None:
    with pytest.raises(NetworkPolicyError) as raised:
        authorize_destination("db.example.com", 22, [ipaddress.ip_address("8.8.8.8")], rules)

    assert raised.value.code == "network_policy.port_denied"


@pytest.mark.parametrize("host", ["http://db.example.com", "user@db", "db/path", "bad_host"])
def test_url_like_or_invalid_hosts_are_rejected(host: str) -> None:
    with pytest.raises(NetworkPolicyError):
        normalize_host(host)


def test_dns_rebinding_is_rejected(rules: NetworkPolicyRules) -> None:
    with pytest.raises(NetworkPolicyError) as raised:
        verify_connected_address(
            ipaddress.ip_address("8.8.4.4"),
            [ipaddress.ip_address("8.8.8.8")],
            rules,
        )

    assert raised.value.code == "network_policy.dns_rebinding"
