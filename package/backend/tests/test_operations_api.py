from pathlib import Path

import app.config as config_module
from app.database import SessionLocal
from app.models.models import AdminAuditLog, OptimizationSession, RegistrationInvite
from app.services import operations_service, update_service
from app.utils.time import utcnow


def _admin_auth_headers(client):
    response = client.post(
        "/api/admin/login",
        json={
            "username": config_module.settings.ADMIN_USERNAME,
            "password": config_module.settings.ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_operations_status_reports_database_worker_backup_and_update(client, monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "gankaigc_ai_polish_20260512_010203.dump"
    backup_file.write_bytes(b"backup-data")

    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", str(backup_dir), raising=False)
    monkeypatch.setattr(update_service, "can_run_vps_update", lambda: (False, "not mounted"))
    monkeypatch.setattr(
        update_service,
        "get_git_revision_status",
        lambda: {
            "source_update_available": None,
            "error": "not a git repo",
        },
    )

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=None,
            session_id="processing-session",
            original_text="hello",
            current_stage="polish",
            status="processing",
            worker_id="worker-1",
            updated_at=utcnow(),
        )
        db.add(session)
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/operations/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    data = response.json()
    assert data["database"]["ok"] is True
    assert data["worker"]["processing_count"] == 1
    assert data["worker"]["last_worker_id"] == "worker-1"
    assert data["backup"]["enabled"] is True
    assert data["backup"]["total_files"] == 1
    assert data["backup"]["latest"]["filename"] == backup_file.name
    assert data["update"]["can_run"] is False
    assert data["update"]["disabled_reason"] == "not mounted"


def test_admin_operations_status_includes_onboarding_checklist(client, monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "gankaigc_ai_polish_20260512_010203.dump").write_bytes(b"backup-data")
    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", str(backup_dir), raising=False)
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "StrongAdminPassword123!", raising=False)
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "strong-secret-key-for-tests", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://api.example/v1", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "gpt-test", raising=False)
    monkeypatch.setattr(update_service, "can_run_vps_update", lambda: (False, "disabled"))
    monkeypatch.setattr(update_service, "get_git_revision_status", lambda: {"source_update_available": None, "error": None})

    db = SessionLocal()
    try:
        db.add(RegistrationInvite(code="READY-INVITE", is_active=True))
        db.add(
            OptimizationSession(
                user_id=None,
                session_id="completed-session",
                original_text="hello",
                current_stage="polish",
                status="completed",
                completed_at=utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/operations/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    checklist = response.json()["onboarding"]
    assert checklist["completed_count"] == checklist["total_count"]
    assert checklist["ready"] is True
    assert {item["key"]: item["done"] for item in checklist["items"]} == {
        "admin_password": True,
        "secret_key": True,
        "model_api": True,
        "invite": True,
        "test_task": True,
        "backup": True,
    }


def test_admin_onboarding_does_not_treat_placeholder_model_api_as_configured(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", None, raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", None, raising=False)
    monkeypatch.setattr(config_module.settings, "OPENAI_API_KEY", "pwd", raising=False)
    monkeypatch.setattr(config_module.settings, "OPENAI_BASE_URL", "http://IP:PORT/v1", raising=False)
    monkeypatch.setattr(update_service, "can_run_vps_update", lambda: (False, "disabled"))
    monkeypatch.setattr(update_service, "get_git_revision_status", lambda: {"source_update_available": None, "error": None})

    response = client.get("/api/admin/operations/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    items = {item["key"]: item["done"] for item in response.json()["onboarding"]["items"]}
    assert items["model_api"] is False


def test_admin_operations_status_is_clear_when_backup_directory_is_missing(client, monkeypatch, tmp_path):
    missing_dir = tmp_path / "missing-backups"
    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", str(missing_dir), raising=False)
    monkeypatch.setattr(update_service, "can_run_vps_update", lambda: (False, "disabled"))
    monkeypatch.setattr(update_service, "get_git_revision_status", lambda: {"source_update_available": None, "error": None})

    response = client.get("/api/admin/operations/status", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    backup = response.json()["backup"]
    assert backup["enabled"] is False
    assert backup["total_files"] == 0
    assert "未检测到备份目录" in backup["message"]


def test_admin_can_download_backup_file(client, monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "gankaigc_ai_polish_20260512_010203.dump"
    backup_file.write_bytes(b"backup-data")
    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", str(backup_dir), raising=False)

    response = client.get(
        f"/api/admin/operations/backups/{backup_file.name}/download",
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert response.content == b"backup-data"


def test_admin_backup_download_rejects_path_traversal(client):
    response = client.get(
        "/api/admin/operations/backups/..%2F.env/download",
        headers=_admin_auth_headers(client),
    )

    assert response.status_code in {400, 404}


def test_admin_model_test_returns_success_and_writes_audit_log(client, monkeypatch):
    async def fake_test_model_connection(stage):
        return {
            "ok": True,
            "stage": stage,
            "label": "润色模型",
            "model": "gpt-test",
            "base_url": "https://api.example/v1",
            "message": "API 连接测试通过",
        }

    monkeypatch.setattr(operations_service, "test_model_connection", fake_test_model_connection)

    response = client.post(
        "/api/admin/operations/model-test",
        json={"stage": "polish"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True

    db = SessionLocal()
    try:
        log = db.query(AdminAuditLog).filter(AdminAuditLog.action == "test_model_connection").one()
        assert "polish" in (log.detail or "")
        assert "gpt-test" in (log.detail or "")
    finally:
        db.close()


def test_admin_model_test_returns_structured_failure(client, monkeypatch):
    async def fake_test_model_connection(stage):
        return {
            "ok": False,
            "stage": stage,
            "label": "润色模型",
            "model": "bad-model",
            "base_url": "https://api.example/v1",
            "message": "模型不存在或当前 Key 无权访问该模型",
        }

    monkeypatch.setattr(operations_service, "test_model_connection", fake_test_model_connection)

    response = client.post(
        "/api/admin/operations/model-test",
        json={"stage": "polish"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["ok"] is False
    assert "模型不存在" in response.json()["detail"]["message"]


def test_backup_status_orders_recent_files_first(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old_file = backup_dir / "gankaigc_ai_polish_20260511_010203.dump"
    new_file = backup_dir / "gankaigc_ai_polish_20260512_010203.dump"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", str(backup_dir), raising=False)
    old_mtime = 1_700_000_000
    new_mtime = 1_800_000_000
    Path(old_file).touch()
    Path(new_file).touch()
    import os

    os.utime(old_file, (old_mtime, old_mtime))
    os.utime(new_file, (new_mtime, new_mtime))

    status = operations_service.get_backup_status()

    assert status["files"][0]["filename"] == new_file.name
    assert status["files"][1]["filename"] == old_file.name


def test_relative_backup_dir_prefers_mounted_source_workdir(monkeypatch, tmp_path):
    mounted_source = tmp_path / "source"
    mounted_source.mkdir()
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    monkeypatch.setattr(config_module.settings, "BACKUP_DIR", "backups", raising=False)
    monkeypatch.setattr(config_module.settings, "VPS_UPDATE_WORKDIR", str(mounted_source), raising=False)
    monkeypatch.setenv("GANKAIGC_HOST_PROJECT_DIR", str(host_dir))

    assert operations_service.get_backup_dir() == mounted_source / "backups"
