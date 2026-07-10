from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_dockerfile_does_not_install_docker_control_tools_in_app_image():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    app_stage = dockerfile.split("FROM ${DOCKER_IMAGE_PREFIX}library/python:3.11-slim AS app", 1)[1]

    assert "ARG DOCKER_COMPOSE_VERSION" not in app_stage
    assert "docker-cli" not in app_stage
    assert "docker.io" not in app_stage
    assert "git config --system --add safe.directory /app/source" not in app_stage
    assert "docker compose version" not in app_stage


def test_dockerfile_copies_packaged_version_file():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY package/VERSION /app/package/VERSION" in dockerfile


def test_docker_healthcheck_uses_process_liveness_endpoint():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "http://127.0.0.1:9800/live" in dockerfile


def test_dockerfile_uses_runtime_allowlist_instead_of_copying_package_tree():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY package/ ./" not in dockerfile
    assert "COPY package/main.py /app/package/main.py" in dockerfile
    assert "COPY package/backend/ /app/package/backend/" in dockerfile
    assert "COPY LICENSE NOTICE /app/licenses/" in dockerfile
    assert "COPY --from=frontend-builder /app/package/frontend/dist ./static" in dockerfile


def test_dockerignore_excludes_secrets_local_state_and_build_caches():
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    patterns = {line.strip() for line in dockerignore if line.strip() and not line.lstrip().startswith("#")}

    assert ".env*" in patterns
    assert "backups/" in patterns
    assert "package/venv/" in patterns
    assert "package/.playwright-browsers/" in patterns
    assert "package/data/" in patterns
    assert "package/uploads/" in patterns
