import ipaddress
import socket
from urllib.parse import urlparse


LOCAL_MODEL_PROXY_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
LOCAL_SERVER_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCAL_PROXY_HELP = (
    "你正在使用本地/内网模型地址。若是 Windows 本地一键包本机使用，请将 SERVER_HOST=127.0.0.1，"
    "打开本地模型代理，并使用 http://127.0.0.1:端口/v1。"
    "若是云端部署，请使用公网 HTTPS Base URL。"
)


def _parse_ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_disallowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or str(address) == "169.254.169.254"
    )


def validate_external_https_url(value: str) -> str:
    """Validate a model provider Base URL before the server makes outbound requests."""
    normalized = (value or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Base URL 未配置")

    try:
        parsed = urlparse(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Base URL 格式不正确") from exc

    if parsed.scheme.lower() != "https":
        raise ValueError("Base URL 必须使用 https://")
    if not parsed.hostname:
        raise ValueError("Base URL 必须包含有效域名")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 禁止包含用户名或密码")

    hostname = parsed.hostname.strip()
    hostname_for_check = hostname.rstrip(".").lower()
    if hostname_for_check in {"localhost"} or hostname_for_check.endswith(".localhost"):
        raise ValueError("Base URL 禁止指向 localhost")

    hostname_ip = _parse_ip_address(hostname_for_check)
    if hostname_ip is None and "." not in hostname_for_check:
        raise ValueError("Base URL 必须使用公网域名，不能使用单标签主机名")

    try:
        addrinfo = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Base URL 域名解析失败") from exc

    resolved_addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for item in addrinfo:
        sockaddr = item[4]
        if not sockaddr:
            continue
        resolved_ip = _parse_ip_address(sockaddr[0])
        if resolved_ip is not None:
            resolved_addresses.add(resolved_ip)

    if not resolved_addresses:
        raise ValueError("Base URL 域名没有解析到有效 IP")

    for address in resolved_addresses:
        if _is_disallowed_address(address):
            raise ValueError(LOCAL_PROXY_HELP)

    return normalized


def _is_local_model_proxy_hostname(hostname: str) -> bool:
    return hostname.rstrip(".").lower() in LOCAL_MODEL_PROXY_HOSTS


def _get_explicit_port(parsed) -> int:
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Base URL 本地代理端口不正确") from exc
    if port is None:
        raise ValueError("Base URL 本地代理必须显式填写端口")
    if port < 1 or port > 65535:
        raise ValueError("Base URL 本地代理端口不正确")
    return port


def _validate_local_model_proxy_url(
    normalized: str,
    parsed,
    *,
    allow_local_model_proxy: bool | None = None,
    server_host: str | None = None,
) -> str:
    if parsed.scheme.lower() != "http":
        raise ValueError("Base URL 本地代理仅允许 http://")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 禁止包含用户名或密码")
    if not parsed.hostname or not _is_local_model_proxy_hostname(parsed.hostname):
        raise ValueError("Base URL 本地代理只能使用 127.0.0.1、localhost、::1 或 host.docker.internal")

    _get_explicit_port(parsed)

    if allow_local_model_proxy is None or server_host is None:
        from app.config import settings

        if allow_local_model_proxy is None:
            allow_local_model_proxy = settings.ALLOW_LOCAL_MODEL_PROXY
        if server_host is None:
            server_host = settings.SERVER_HOST

    if not allow_local_model_proxy:
        raise ValueError(
            "Base URL 本地代理未启用。若是 Windows 一键包本机使用，请打开本地模型代理；"
            "若是云端部署，请使用公网 HTTPS Base URL。"
        )

    normalized_server_host = (server_host or "").strip().rstrip(".").lower()
    if normalized_server_host not in LOCAL_SERVER_HOSTS:
        raise ValueError(
            "Base URL 本地代理只允许在 SERVER_HOST=127.0.0.1、localhost 或 ::1 时使用。"
            "公网或 0.0.0.0 部署请改用公网 HTTPS Base URL。"
        )

    return normalized


def validate_model_base_url(
    value: str,
    *,
    allow_local_model_proxy: bool | None = None,
    server_host: str | None = None,
) -> str:
    """Validate model Base URL, allowing only public HTTPS or explicit local proxy mode."""
    normalized = (value or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Base URL 未配置")

    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise ValueError("Base URL 格式不正确") from exc

    if parsed.username or parsed.password:
        raise ValueError("Base URL 禁止包含用户名或密码")
    if not parsed.hostname:
        raise ValueError("Base URL 必须包含有效域名")

    if parsed.scheme.lower() == "http":
        return _validate_local_model_proxy_url(
            normalized,
            parsed,
            allow_local_model_proxy=allow_local_model_proxy,
            server_host=server_host,
        )

    return validate_external_https_url(normalized)
