from __future__ import annotations

from contextvars import ContextVar, Token
import ipaddress

from fastapi import Request

from app.config import settings


_current_client_ip: ContextVar[str | None] = ContextVar(
    "gankaigc_current_client_ip",
    default=None,
)


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _trusted_proxy_networks():
    networks = []
    for raw_value in settings.TRUSTED_PROXY_IPS.split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_proxy(address) -> bool:
    return any(address in network for network in _trusted_proxy_networks())


def resolve_request_client_ip(request: Request) -> str | None:
    direct_ip = _parse_ip(request.client.host if request.client else None)
    if direct_ip is None:
        return None
    if not _is_trusted_proxy(direct_ip):
        return str(direct_ip)

    forwarded_chain = [
        parsed
        for item in request.headers.get("x-forwarded-for", "").split(",")
        if (parsed := _parse_ip(item)) is not None
    ]
    chain = forwarded_chain + [direct_ip]
    while chain and _is_trusted_proxy(chain[-1]):
        chain.pop()
    return str(chain[-1] if chain else direct_ip)


def set_current_client_ip(value: str | None) -> Token:
    return _current_client_ip.set(value)


def reset_current_client_ip(token: Token) -> None:
    _current_client_ip.reset(token)


def get_current_client_ip() -> str | None:
    return _current_client_ip.get()
