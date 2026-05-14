import importlib.util
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MAIN = PACKAGE_ROOT / "main.py"


@pytest.fixture(autouse=True)
def reset_db():
    yield


def _load_package_main():
    previous_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location(
        "gankaigc_package_main_static_security_tests",
        PACKAGE_MAIN,
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(previous_cwd)


def test_static_fallback_rejects_encoded_path_traversal():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    for path in (
        "/%2e%2e%2fmain.py",
        "/..%2Fmain.py",
        "/%2E%2E/main.py",
        "/%2e%2e%2f.env",
    ):
        response = client.get(path)

        assert response.status_code == 404


def test_static_fallback_serves_existing_static_file():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    response = client.get("/sample-paper.md")

    assert response.status_code == 200
    assert "基于深度学习的图像识别技术研究" in response.text


def test_static_fallback_keeps_spa_route_fallback():
    package_main = _load_package_main()
    client = TestClient(package_main.app)

    response = client.get("/unmatched/spa/route")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
