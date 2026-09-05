import ipaddress
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
_METADATA_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


class NetworkPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NetworkPolicyRules:
    allowed_private_cidrs: tuple[IPNetwork, ...]
    allowed_ports: frozenset[int]

    @classmethod
    def from_strings(
        cls,
        *,
        allowed_private_cidrs: Iterable[str],
        allowed_ports: Iterable[int],
    ) -> "NetworkPolicyRules":
        try:
            cidrs = tuple(
                ipaddress.ip_network(value, strict=True) for value in allowed_private_cidrs
            )
        except ValueError as exc:
            raise NetworkPolicyError("network_policy.invalid_cidr", str(exc)) from exc
        ports = frozenset(allowed_ports)
        if not ports or any(port < 1 or port > 65535 for port in ports):
            raise NetworkPolicyError(
                "network_policy.invalid_port", "Allowed ports must be between 1 and 65535"
            )
        return cls(allowed_private_cidrs=cidrs, allowed_ports=ports)


def normalize_host(host: str) -> str:
    normalized = host.strip().rstrip(".").lower()
    if not normalized or any(marker in normalized for marker in ("://", "/", "@", "\\")):
        raise NetworkPolicyError("network_policy.invalid_host", "Host must not contain a URL")
    try:
        ipaddress.ip_address(normalized)
        return normalized
    except ValueError:
        pass
    try:
        ascii_host = normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise NetworkPolicyError("network_policy.invalid_host", "Host name is invalid") from exc
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise NetworkPolicyError("network_policy.invalid_host", "Host name is invalid")
    return ascii_host


def resolve_host(host: str) -> tuple[IPAddress, ...]:
    normalized = normalize_host(host)
    try:
        return (ipaddress.ip_address(normalized),)
    except ValueError:
        pass
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise NetworkPolicyError("network_policy.dns_failed", "Host could not be resolved") from exc
    if not addresses:
        raise NetworkPolicyError("network_policy.dns_failed", "Host returned no addresses")
    return tuple(sorted(addresses, key=str))


def _is_denied_class(address: IPAddress) -> bool:
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or any(
            address.version == network.version and address in network
            for network in _METADATA_NETWORKS
        )
    )


def _is_explicitly_allowed(address: IPAddress, rules: NetworkPolicyRules) -> bool:
    return any(
        address.version == network.version and address in network
        for network in rules.allowed_private_cidrs
    )


def _authorize_address(address: IPAddress, rules: NetworkPolicyRules) -> None:
    if _is_denied_class(address):
        raise NetworkPolicyError(
            "network_policy.address_denied", "Destination address class is denied"
        )
    if address.is_private and not _is_explicitly_allowed(address, rules):
        raise NetworkPolicyError(
            "network_policy.private_address_denied",
            "Private destination is outside the configured allowlist",
        )


def authorize_destination(
    host: str,
    port: int,
    resolved_addresses: Iterable[IPAddress],
    rules: NetworkPolicyRules,
) -> tuple[IPAddress, ...]:
    normalize_host(host)
    if port not in rules.allowed_ports:
        raise NetworkPolicyError("network_policy.port_denied", "Destination port is not allowed")
    addresses = tuple(sorted(set(resolved_addresses), key=str))
    if not addresses:
        raise NetworkPolicyError("network_policy.dns_failed", "Host returned no addresses")
    for address in addresses:
        _authorize_address(address, rules)
    return addresses


def verify_connected_address(
    connected_address: IPAddress,
    initially_authorized: Iterable[IPAddress],
    rules: NetworkPolicyRules,
) -> None:
    initial = set(initially_authorized)
    if connected_address not in initial:
        raise NetworkPolicyError(
            "network_policy.dns_rebinding", "Connected address differs from DNS authorization"
        )
    _authorize_address(connected_address, rules)
