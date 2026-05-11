from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_default_docker_compose_includes_vps_update_mounts():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "GANKAIGC_HOST_PROJECT_DIR" in compose
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}" in compose
    assert "target: /app/source" in compose
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/.env.docker" in compose
    assert "target: /app/config/.env.docker" in compose
    assert "- ./:/app/source" not in compose
    assert "- /var/run/docker.sock:/var/run/docker.sock" in compose
    assert "updater:" in compose
    assert "profiles:" in compose
    assert "- update" in compose


def test_default_docker_compose_includes_postgres_backup_service():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  backup:" in compose
    assert "docker-postgres-backup.sh" in compose
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/backups" in compose
    assert "target: /backups" in compose
    assert "BACKUP_RETENTION_DAYS" in compose
    assert "BACKUP_INTERVAL_SECONDS" in compose
    assert "condition: service_healthy" in compose


def test_docker_env_example_enables_vps_update_by_default():
    env_example = (PROJECT_ROOT / ".env.docker.example").read_text(encoding="utf-8")

    assert "VPS_UPDATE_ENABLED=true" in env_example
    assert "BACKUP_RETENTION_DAYS=14" in env_example
    assert "BACKUP_INTERVAL_SECONDS=86400" in env_example
    assert "docker-compose.update.yml" not in env_example
