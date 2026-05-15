import importlib.util
import os
from pathlib import Path

from fastapi.testclient import TestClient


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MAIN = PACKAGE_ROOT / "main.py"


def _assert_common_security_headers(response):
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert "microphone=()" in response.headers["Permissions-Policy"]

    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "connect-src 'self'" in csp


def _load_package_main():
    previous_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location(
        "gankaigc_package_main_security_headers_tests",
        PACKAGE_MAIN,
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(previous_cwd)


def test_api_response_has_security_headers(client):
    response = client.get("/health")

    assert response.status_code == 200
    _assert_common_security_headers(response)


def test_rate_limited_response_has_security_headers(client, monkeypatch):
    from app.config import settings
    from app.main import auth_rate_limiter

    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_PER_MINUTE", 1)
    auth_rate_limiter.reset()

    payload = {"username": "missing", "password": "wrong-password"}
    assert client.post("/api/auth/login", json=payload).status_code == 401
    response = client.post("/api/auth/login", json=payload)

    assert response.status_code == 429
    _assert_common_security_headers(response)


def test_docs_response_allows_fastapi_swagger_assets(client):
    response = client.get("/docs")

    assert response.status_code == 200
    _assert_common_security_headers(response)
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "img-src 'self' data: blob: https://fastapi.tiangolo.com" in csp


def test_packaged_spa_response_has_security_headers():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    response = client.get("/admin")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    _assert_common_security_headers(response)
    assert "'sha256-" in response.headers["Content-Security-Policy"]


def test_packaged_docs_response_allows_fastapi_swagger_assets():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    response = client.get("/docs")

    assert response.status_code == 200
    _assert_common_security_headers(response)
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
    assert "img-src 'self' data: blob: https://fastapi.tiangolo.com" in csp


def test_packaged_static_file_response_has_security_headers():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    response = client.get("/gankaigc-logo.svg")

    assert response.status_code == 200
    _assert_common_security_headers(response)
