from starlette.requests import Request

import app.config as config_module
from app.utils.client_ip import resolve_request_client_ip


def _request(client_ip: str, forwarded_for: str = "") -> Request:
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_ip, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_untrusted_direct_peer_cannot_spoof_forwarded_client_ip(monkeypatch):
    monkeypatch.setattr(config_module.settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    request = _request("203.0.113.20", "198.51.100.99")

    assert resolve_request_client_ip(request) == "203.0.113.20"


def test_trusted_proxy_chain_selects_nearest_untrusted_client(monkeypatch):
    monkeypatch.setattr(
        config_module.settings,
        "TRUSTED_PROXY_IPS",
        "127.0.0.1,10.0.0.0/8",
    )
    request = _request("127.0.0.1", "198.51.100.99, 203.0.113.20, 10.0.0.2")

    assert resolve_request_client_ip(request) == "203.0.113.20"
