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
    assert "collected_at" in data
    assert data["system"]["cpu"]["logical_cpus"] >= 1
    assert "percent" in data["system"]["cpu"]
    assert "memory" in data["system"]
    assert "disk" in data["system"]
    assert "network" in data["system"]
    assert "load" in data["system"]
    assert data["database"]["ok"] is True
    assert data["database"]["average_latency_ms"] is not None
    assert len(data["database"]["latency_samples_ms"]) >= 1
    assert "slow_query_count" in data["database"]
    assert data["worker"]["processing_count"] == 1
    assert data["worker"]["capacity"] >= 1
    assert "available_slots" in data["worker"]
    assert data["worker"]["last_worker_id"] == "worker-1"
    assert len(data["models"]["items"]) == 4
    assert {item["stage"] for item in data["models"]["items"]} == {"polish", "enhance", "emotion", "compression"}
    assert "scheduled_count" in data["jobs"]
    assert isinstance(data["events"], list)
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


def test_operations_status_helpers_return_unavailable_when_database_queries_fail(tmp_path):
    class BrokenQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def count(self):
            raise RuntimeError("database down")

        def first(self):
            raise RuntimeError("database down")

        def all(self):
            raise RuntimeError("database down")

    class BrokenSession:
        def query(self, *args, **kwargs):
            return BrokenQuery()

        def rollback(self):
            self.rolled_back = True

    session = BrokenSession()
    backup_status = {
        "enabled": False,
        "total_files": 0,
        "latest": None,
    }
    database_status = {"ok": False, "message": "database down"}
    worker_status = operations_service.get_worker_status(session)
    jobs = operations_service.get_job_status(session, backup_status, worker_status)
    events = operations_service.get_operations_events(session, database_status, worker_status, backup_status)
    onboarding = operations_service.get_onboarding_status(session, backup_status)

    assert worker_status["ok"] is False
    assert "无法读取任务队列状态" in worker_status["message"]
    assert jobs["completed_count"] is None
    assert events[0]["badge"] == "异常"
    assert onboarding["ready"] is False


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


def test_admin_model_config_rejects_private_base_url_before_connection(monkeypatch):
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "gpt-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://127.0.0.1/v1", raising=False)

    try:
        operations_service.get_model_config("polish")
    except ValueError as exc:
        assert "Base URL" in str(exc)
    else:
        raise AssertionError("private Base URL should be rejected")


def test_admin_model_config_accepts_local_proxy_in_local_mode(monkeypatch):
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "gpt-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "http://host.docker.internal:8317/v1", raising=False)
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "localhost", raising=False)

    config = operations_service.get_model_config("polish")

    assert config["base_url"] == "http://host.docker.internal:8317/v1"


def test_model_health_url_check_rejects_private_base_url():
    from app.main import _check_url_format

    is_valid, error = _check_url_format("https://127.0.0.1/v1")

    assert is_valid is False
    assert "Base URL" in error


def test_model_health_url_check_accepts_local_proxy_in_local_mode(monkeypatch):
    from app.main import _check_url_format

    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    is_valid, error = _check_url_format("http://127.0.0.1:8317/v1")

    assert is_valid is True
    assert error is None


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


def test_list_provider_models_fetches_openai_compatible_model_ids(monkeypatch):
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "http://127.0.0.1:8317/v1", raising=False)
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "object": "list",
                "data": [
                    {"id": "gpt-5.5", "object": "model"},
                    {"id": "gpt-4o", "object": "model"},
                    {"id": "gpt-5.5", "object": "model"},
                ],
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(operations_service.httpx, "AsyncClient", FakeAsyncClient)

    import asyncio

    result = asyncio.run(operations_service.list_provider_models("polish"))

    assert result["ok"] is True
    assert result["models"] == ["gpt-5.5", "gpt-4o"]
    assert result["count"] == 2
    assert captured["url"] == "http://127.0.0.1:8317/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer sk-test"}


def test_admin_model_list_returns_success_and_does_not_audit_api_key(client, monkeypatch):
    async def fake_list_provider_models(stage, *, base_url=None, api_key=None):
        assert stage == "polish"
        assert base_url == "https://api.example/v1"
        assert api_key == "sk-transient-secret"
        return {
            "ok": True,
            "stage": stage,
            "label": "润色模型",
            "base_url": base_url,
            "models": ["gpt-5.5", "gpt-4o"],
            "count": 2,
            "message": "已拉取 2 个模型",
        }

    monkeypatch.setattr(operations_service, "list_provider_models", fake_list_provider_models)

    response = client.post(
        "/api/admin/operations/model-list",
        json={
            "stage": "polish",
            "base_url": "https://api.example/v1",
            "api_key": "sk-transient-secret",
        },
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["gpt-5.5", "gpt-4o"]

    db = SessionLocal()
    try:
        log = db.query(AdminAuditLog).filter(AdminAuditLog.action == "list_provider_models").one()
        assert "sk-transient-secret" not in (log.detail or "")
        assert "gpt-5.5" not in (log.detail or "")
        assert "model_count" in (log.detail or "")
    finally:
        db.close()


def test_admin_model_list_returns_structured_failure(client, monkeypatch):
    async def fake_list_provider_models(stage, *, base_url=None, api_key=None):
        return {
            "ok": False,
            "stage": stage,
            "label": "润色模型",
            "base_url": base_url,
            "models": [],
            "count": 0,
            "message": "API Key 未配置",
        }

    monkeypatch.setattr(operations_service, "list_provider_models", fake_list_provider_models)

    response = client.post(
        "/api/admin/operations/model-list",
        json={"stage": "polish", "base_url": "https://api.example/v1"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["ok"] is False
    assert response.json()["detail"]["message"] == "API Key 未配置"
