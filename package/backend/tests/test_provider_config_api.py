import socket
from types import SimpleNamespace

from cryptography.fernet import Fernet

import app.config as config_module
from app.database import SessionLocal
from app.models.models import OptimizationSession, User, UserProviderConfig
from app.utils.auth import create_user_access_token, get_password_hash


def _admin_auth_headers(client):
    response = client.post(
        "/api/admin/login",
        json={"username": config_module.settings.ADMIN_USERNAME, "password": config_module.settings.ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class NoRunBackgroundTasks:
    def add_task(self, *args, **kwargs):
        return None


def _allow_public_model_url_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )


def _create_user(username="alice"):
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=get_password_hash("Password123!"),
            access_link=f"http://testserver/access/{username}",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
        return user.id, token
    finally:
        db.close()


def test_saved_provider_config_is_not_returned_in_plaintext(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    _allow_public_model_url_dns(monkeypatch)
    user_id, token = _create_user()

    payload = {
        "base_url": "https://api.example/v1/",
        "api_format": "openai_chat",
        "api_key": "sk-test-secret",
        "polish_model": "gpt-5.4",
        "enhance_model": "gpt-5.4",
        "emotion_model": "gpt-5.4-mini",
    }

    put_response = client.put(
        "/api/user/provider-config",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert put_response.status_code == 200
    assert put_response.json() == {
        "base_url": "https://api.example/v1",
        "api_format": "openai_chat",
        "api_key_last4": "cret",
        "polish_model": "gpt-5.4",
        "enhance_model": "gpt-5.4",
        "emotion_model": "gpt-5.4-mini",
    }

    get_response = client.get("/api/user/provider-config", headers={"Authorization": f"Bearer {token}"})

    assert get_response.status_code == 200
    assert "sk-test-secret" not in get_response.text
    assert get_response.json()["api_key_last4"] == "cret"

    db = SessionLocal()
    try:
        config = db.query(UserProviderConfig).filter(UserProviderConfig.user_id == user_id).one()
        assert config.api_format == "openai_chat"
        assert config.api_key_encrypted != "sk-test-secret"
        assert config.api_key_last4 == "cret"
    finally:
        db.close()


def test_admin_provider_config_summary_masks_user_api_key(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    _allow_public_model_url_dns(monkeypatch)
    _, token = _create_user()
    client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.example/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
            "emotion_model": "gpt-5.4-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.get("/api/admin/provider-configs", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    assert "sk-test-secret" not in response.text
    assert response.json() == [
        {
            "user_id": 1,
            "username": "alice",
            "base_url": "https://api.example/v1",
            "api_format": "openai_chat",
            "api_key_last4": "cret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
            "emotion_model": "gpt-5.4-mini",
            "updated_at": response.json()[0]["updated_at"],
        }
    ]


def test_provider_config_rejects_localhost_base_url(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    user_id, token = _create_user()

    response = client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://localhost/v1",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Base URL" in response.json()["detail"]

    db = SessionLocal()
    try:
        assert db.query(UserProviderConfig).filter(UserProviderConfig.user_id == user_id).first() is None
    finally:
        db.close()


def test_provider_config_accepts_local_http_proxy_only_in_local_mode(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)
    user_id, token = _create_user()

    response = client.put(
        "/api/user/provider-config",
        json={
            "base_url": "http://127.0.0.1:8317/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["base_url"] == "http://127.0.0.1:8317/v1"

    db = SessionLocal()
    try:
        config = db.query(UserProviderConfig).filter(UserProviderConfig.user_id == user_id).one()
        assert config.base_url == "http://127.0.0.1:8317/v1"
    finally:
        db.close()


def test_provider_config_rejects_local_http_proxy_when_server_is_exposed(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "0.0.0.0", raising=False)
    user_id, token = _create_user()

    response = client.put(
        "/api/user/provider-config",
        json={
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Base URL" in response.json()["detail"]

    db = SessionLocal()
    try:
        assert db.query(UserProviderConfig).filter(UserProviderConfig.user_id == user_id).first() is None
    finally:
        db.close()


def test_provider_config_test_makes_real_model_request(client, monkeypatch):
    import app.services.operations_service as operations_service

    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="chatcmpl-test")

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(operations_service, "AsyncOpenAI", FakeAsyncOpenAI)
    _allow_public_model_url_dns(monkeypatch)
    _, token = _create_user()
    client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.example/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.post("/api/user/provider-config/test", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["message"] == "API 连接测试通过"
    assert calls == [
        {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "temperature": 0,
        }
    ]


def test_provider_config_test_rejects_failed_model_request(client, monkeypatch):
    import app.services.operations_service as operations_service

    class FakeCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("invalid api key")

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(operations_service, "AsyncOpenAI", FakeAsyncOpenAI)
    _allow_public_model_url_dns(monkeypatch)
    _, token = _create_user()
    client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.example/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.post("/api/user/provider-config/test", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400
    assert response.json()["detail"]["ok"] is False
    assert response.json()["detail"]["message"] == "invalid api key"



def test_provider_config_test_uses_anthropic_messages_endpoint(client, monkeypatch):
    import app.services.operations_service as operations_service

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "msg-test", "content": [{"type": "text", "text": "pong"}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(operations_service.httpx, "AsyncClient", FakeAsyncClient)
    _allow_public_model_url_dns(monkeypatch)
    _, token = _create_user()
    save_response = client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.anthropic.com",
            "api_format": "anthropic",
            "api_key": "sk-ant-secret",
            "polish_model": "claude-sonnet-4-5",
            "enhance_model": "claude-sonnet-4-5",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert save_response.status_code == 200
    assert save_response.json()["api_format"] == "anthropic"

    response = client.post("/api/user/provider-config/test", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["api_format"] == "anthropic"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-secret"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["model"] == "claude-sonnet-4-5"
    assert captured["json"]["max_tokens"] == 8
    assert captured["json"]["messages"] == [{"role": "user", "content": "ping"}]

def test_byok_start_requires_saved_user_provider(client):
    _, token = _create_user()

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "test paragraph",
            "processing_mode": "paper_polish",
            "billing_mode": "byok",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先保存自带 API 配置"


def test_byok_start_optimization_uses_saved_user_provider(client, monkeypatch):
    from app.routes import optimization

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    _allow_public_model_url_dns(monkeypatch)
    user_id, token = _create_user()
    client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.example/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.4",
            "enhance_model": "gpt-5.4",
            "emotion_model": "gpt-5.4-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "test paragraph",
            "processing_mode": "paper_polish",
            "billing_mode": "byok",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["credential_source"] == "user_saved"
    assert response.json()["charge_status"] == "not_charged"

    db = SessionLocal()
    try:
        session = db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).one()
        user = db.query(User).filter(User.id == user_id).one()
        assert user.credit_balance == 0
        assert session.polish_model == "gpt-5.4"
        assert session.polish_base_url == "https://api.example/v1"
        assert session.polish_api_format == "openai_chat"
        assert session.enhance_api_format == "openai_chat"
        assert session.emotion_api_format == "openai_chat"
        assert session.polish_api_key is None
        assert session.credential_source == "user_saved"
    finally:
        db.close()


def test_retry_failed_session_can_switch_to_saved_user_provider(client, monkeypatch):
    from app.routes import optimization

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", lambda *args, **kwargs: None)
    _allow_public_model_url_dns(monkeypatch)
    user_id, token = _create_user()
    client.put(
        "/api/user/provider-config",
        json={
            "base_url": "https://api.example/v1/",
            "api_key": "sk-test-secret",
            "polish_model": "gpt-5.5",
            "enhance_model": "gpt-5.5",
            "emotion_model": "gpt-5.4-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    db = SessionLocal()
    try:
        failed_session = OptimizationSession(
            user_id=user_id,
            session_id="failed-platform-session",
            original_text="test paragraph",
            current_stage="polish",
            status="failed",
            error_message="platform api failed",
            billing_mode="platform",
            credential_source="system",
            charge_status="refunded",
            charged_credits=0,
            polish_model="bad-platform-model",
            polish_base_url="https://bad.example/v1",
        )
        db.add(failed_session)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/optimization/sessions/failed-platform-session/retry",
        json={"billing_mode": "byok"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["billing_mode"] == "byok"
    assert response.json()["credential_source"] == "user_saved"

    db = SessionLocal()
    try:
        session = db.query(OptimizationSession).filter(OptimizationSession.session_id == "failed-platform-session").one()
        user = db.query(User).filter(User.id == user_id).one()
        assert user.credit_balance == 0
        assert session.status == "queued"
        assert session.billing_mode == "byok"
        assert session.credential_source == "user_saved"
        assert session.charge_status == "not_charged"
        assert session.charged_credits == 0
        assert session.polish_model == "gpt-5.5"
        assert session.enhance_model == "gpt-5.5"
        assert session.emotion_model == "gpt-5.4-mini"
        assert session.polish_base_url == "https://api.example/v1"
        assert session.enhance_base_url == "https://api.example/v1"
        assert session.emotion_base_url == "https://api.example/v1"
        assert session.polish_api_format == "openai_chat"
        assert session.enhance_api_format == "openai_chat"
        assert session.emotion_api_format == "openai_chat"
        assert session.polish_api_key is None
        assert session.enhance_api_key is None
        assert session.emotion_api_key is None
    finally:
        db.close()
