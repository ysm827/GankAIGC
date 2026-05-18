import socket

import pytest

import app.config as config_module


def _fake_getaddrinfo(*addresses):
    def fake(host, port, *args, **kwargs):
        results = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port or 443, 0, 0) if family == socket.AF_INET6 else (address, port or 443)
            results.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return results

    return fake


def test_external_https_url_is_normalized_after_dns_resolves_to_public_ip(monkeypatch):
    from app.utils.url_security import validate_external_https_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    assert validate_external_https_url("  https://api.openai.com/v1/  ") == "https://api.openai.com/v1"


def test_external_https_url_preserves_nested_path(monkeypatch):
    from app.utils.url_security import validate_external_https_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    assert (
        validate_external_https_url("https://gateway.example.com/openai/deployments/prod/")
        == "https://gateway.example.com/openai/deployments/prod"
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://api.openai.com/v1",
        "https:///v1",
        "https://user:pass@api.openai.com/v1",
        "https://localhost/v1",
        "https://api.localhost/v1",
        "https://internal/v1",
    ],
)
def test_external_https_url_rejects_unsafe_url_shapes(value, monkeypatch):
    from app.utils.url_security import validate_external_https_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    with pytest.raises(ValueError):
        validate_external_https_url(value)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "172.16.0.8",
        "192.168.1.8",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_external_https_url_rejects_private_or_special_resolved_addresses(address, monkeypatch):
    from app.utils.url_security import validate_external_https_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(address))

    with pytest.raises(ValueError):
        validate_external_https_url("https://api.openai.com/v1")


def test_external_https_url_rejects_if_any_resolved_address_is_private(monkeypatch):
    from app.utils.url_security import validate_external_https_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8", "10.0.0.8"))

    with pytest.raises(ValueError):
        validate_external_https_url("https://api.openai.com/v1")


def test_model_base_url_explains_local_https_proxy_setup(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))

    with pytest.raises(ValueError) as exc_info:
        validate_model_base_url("https://127.0.0.1:8317/v1")

    message = str(exc_info.value)
    assert "本地一键包" in message
    assert "http://127.0.0.1:端口/v1" in message
    assert "公网 HTTPS" in message


def test_model_base_url_explains_private_network_url_setup(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10"))

    with pytest.raises(ValueError) as exc_info:
        validate_model_base_url("https://api.example.com/v1")

    message = str(exc_info.value)
    assert "本地/内网" in message
    assert "云端部署" in message
    assert "公网 HTTPS" in message


def test_external_https_url_rejects_unresolvable_hostname(monkeypatch):
    from app.utils.url_security import validate_external_https_url

    def fail_dns(*args, **kwargs):
        raise socket.gaierror("not found")

    monkeypatch.setattr(socket, "getaddrinfo", fail_dns)

    with pytest.raises(ValueError):
        validate_external_https_url("https://api.openai.com/v1")


def test_model_base_url_accepts_public_https_url(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    assert validate_model_base_url("  https://api.openai.com/v1/  ") == "https://api.openai.com/v1"


def test_model_base_url_rejects_local_http_proxy_by_default(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", False, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    with pytest.raises(ValueError) as exc_info:
        validate_model_base_url("http://127.0.0.1:8317/v1")
    assert "打开本地模型代理" in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:8317/v1/",
        "http://localhost:3000/v1",
        "http://[::1]:8080/v1",
        "http://host.docker.internal:8317/v1",
    ],
)
def test_model_base_url_allows_local_http_proxy_when_enabled_and_server_is_local(value, monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    assert validate_model_base_url(value) == value.rstrip("/")


def test_model_base_url_rejects_local_http_proxy_when_server_is_exposed(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "0.0.0.0", raising=False)

    with pytest.raises(ValueError) as exc_info:
        validate_model_base_url("http://127.0.0.1:8317/v1")
    assert "SERVER_HOST=127.0.0.1" in str(exc_info.value)


def test_model_base_url_uses_hot_reloaded_server_host(monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    assert validate_model_base_url("http://127.0.0.1:8317/v1") == "http://127.0.0.1:8317/v1"


@pytest.mark.parametrize(
    "value",
    [
        "http://192.168.1.10:8317/v1",
        "http://10.0.0.1:8317/v1",
        "http://172.16.0.10:8317/v1",
        "http://proxy.example.com/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:65536/v1",
        "http://user:pass@127.0.0.1:8317/v1",
    ],
)
def test_model_base_url_rejects_unsafe_or_ambiguous_http_urls(value, monkeypatch):
    from app.utils.url_security import validate_model_base_url

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    with pytest.raises(ValueError):
        validate_model_base_url(value)
