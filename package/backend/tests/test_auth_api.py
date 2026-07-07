from pathlib import Path
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from starlette.requests import Request

import app.config as config_module
from app.main import _get_rate_limit_key
from app.utils.crypto import decrypt_secret, encrypt_secret
from app.utils.auth import create_access_token, verify_token
from app.utils.time import utc_naive_now, utcnow


def _admin_auth_headers(client):
    response = client.post(
        "/api/admin/login",
        json={"username": config_module.settings.ADMIN_USERNAME, "password": config_module.settings.ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_auth_endpoints_require_non_default_runtime_secrets(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_project_business_time_uses_china_timezone_but_jwt_uses_utc():
    business_now = utcnow()
    token_now = utc_naive_now()

    # 中国业务时间写入数据库，避免后台/历史列表直查时少 8 小时。
    assert 7.5 * 3600 <= (business_now - token_now).total_seconds() <= 8.5 * 3600

    token = create_access_token({"sub": "time-check", "role": "admin"}, expires_delta=timedelta(minutes=5))
    payload = verify_token(token)
    assert payload


def test_register_requires_valid_invite(client):
    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": "bad-code",
            "username": "alice",
            "password": "Password123!",
        },
    )

    assert response.status_code == 400


def test_login_returns_user_token(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        db.add(
            User(
                username="alice",
                password_hash=get_password_hash("Password123!"),
                access_link="http://testserver/access/alice",
                is_active=True,
                credit_balance=0,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login",
        json={
            "username": "alice",
            "password": "Password123!",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_banned_user_with_correct_password_login_returns_forbidden(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        db.add(
            User(
                username="banned_alice",
                password_hash=get_password_hash("Password123!"),
                access_link="http://testserver/access/banned-alice",
                is_active=False,
                credit_balance=0,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login",
        json={"username": "banned_alice", "password": "Password123!"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "账号已被封禁，请联系管理员"


def test_banned_user_with_wrong_password_does_not_disclose_ban(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        db.add(
            User(
                username="banned_bob",
                password_hash=get_password_hash("Password123!"),
                access_link="http://testserver/access/banned-bob",
                is_active=False,
                credit_balance=0,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login",
        json={"username": "banned_bob", "password": "WrongPassword123!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"


def test_register_with_invite_creates_user_and_disables_invite(client):
    from app.database import SessionLocal
    from app.models.models import RegistrationInvite

    db = SessionLocal()
    try:
        db.add(RegistrationInvite(code="INVITE123", is_active=True))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": "INVITE123",
            "username": "alice",
            "password": "Password123!",
        },
    )

    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert response.json()["nickname"] == "alice"

    db = SessionLocal()
    try:
        invite = db.query(RegistrationInvite).filter(RegistrationInvite.code == "INVITE123").one()
        assert invite.is_active is False
        assert invite.used_by_user_id == response.json()["id"]
    finally:
        db.close()


def test_register_is_blocked_when_registration_is_disabled(client, monkeypatch):
    from app.database import SessionLocal
    from app.models.models import RegistrationInvite, User

    monkeypatch.setattr(config_module.settings, "REGISTRATION_ENABLED", False, raising=False)

    db = SessionLocal()
    try:
        db.add(RegistrationInvite(code="INVITE123", is_active=True))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/register",
        json={
            "invite_code": "INVITE123",
            "username": "alice",
            "password": "Password123!",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "当前已关闭新用户注册"

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username == "alice").first() is None
        invite = db.query(RegistrationInvite).filter(RegistrationInvite.code == "INVITE123").one()
        assert invite.is_active is True
        assert invite.used_by_user_id is None
    finally:
        db.close()


def test_user_me_returns_profile_for_bearer_token(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            nickname="Alice Chen",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=3,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert response.json()["nickname"] == "Alice Chen"
    assert response.json()["credit_balance"] == 3
    assert response.json()["created_at"]


def test_user_can_upload_profile_avatar_and_me_returns_url(client, tmp_path, monkeypatch):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils import avatar_upload
    from app.utils.auth import create_user_access_token, get_password_hash

    monkeypatch.setattr(avatar_upload, "get_upload_root", lambda: tmp_path / "uploads")

    db = SessionLocal()
    try:
        user = User(
            username="avatar_alice",
            nickname="Avatar Alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/avatar-alice",
            is_active=True,
            credit_balance=3,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    png = b"\x89PNG\r\n\x1a\n" + (b"1" * 64)
    response = client.post(
        "/api/user/profile/avatar",
        headers={"Authorization": f"Bearer {token}"},
        files={"avatar": ("profile.png", png, "image/png")},
    )

    assert response.status_code == 200
    avatar_url = response.json()["avatar_url"]
    assert avatar_url.startswith("/uploads/avatars/")
    assert (tmp_path / "uploads" / avatar_url.removeprefix("/uploads/")).read_bytes() == png

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        assert user.avatar_url == avatar_url
    finally:
        db.close()

    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["avatar_url"] == avatar_url


def test_user_profile_avatar_upload_rejects_fake_jpeg(client, tmp_path, monkeypatch):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils import avatar_upload
    from app.utils.auth import create_user_access_token, get_password_hash

    monkeypatch.setattr(avatar_upload, "get_upload_root", lambda: tmp_path / "uploads")

    db = SessionLocal()
    try:
        user = User(
            username="fake_jpeg_alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/fake-jpeg-alice",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.post(
        "/api/user/profile/avatar",
        headers={"Authorization": f"Bearer {token}"},
        files={"avatar": ("profile.jpg", b"not-a-real-jpeg", "image/jpeg")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "头像文件格式不正确"



def test_user_me_rejects_token_after_user_is_banned(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="token_banned_alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/token-banned-alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
        user.is_active = False
        db.commit()
    finally:
        db.close()

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "用户不存在或已禁用"


def test_user_can_update_own_nickname(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
        user_id = user.id
    finally:
        db.close()

    response = client.patch(
        "/api/auth/me",
        json={"nickname": "小艾"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["nickname"] == "小艾"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        assert user.nickname == "小艾"
    finally:
        db.close()


def test_user_nickname_rejects_blank_value(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.patch(
        "/api/auth/me",
        json={"nickname": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


def test_user_can_change_own_password_and_login_with_new_password(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "Password123!", "new_password": "NewPassword456!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "密码已更新"

    old_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "Password123!"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "NewPassword456!"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["access_token"]


def test_user_password_change_invalidates_existing_token(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        old_token = create_user_access_token(user.id, user.username, token_version=user.token_version or 0)
    finally:
        db.close()

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "Password123!", "new_password": "NewPassword456!"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert response.status_code == 200

    old_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert old_me.status_code == 401
    assert old_me.json()["detail"] == "登录状态已失效，请重新登录"

    new_login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "NewPassword456!"},
    )
    assert new_login.status_code == 200
    new_token = new_login.json()["access_token"]

    new_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.status_code == 200


def test_user_change_password_requires_current_password(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "WrongPassword123!", "new_password": "NewPassword456!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "当前密码错误"


def test_user_change_password_rejects_same_password(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import create_user_access_token, get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
    finally:
        db.close()

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "Password123!", "new_password": "Password123!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "新密码不能和当前密码相同"


def test_admin_can_create_list_and_toggle_registration_invites(client):
    headers = _admin_auth_headers(client)

    create_response = client.post(
        "/api/admin/invites",
        json={"code": "INVITE123"},
        headers=headers,
    )

    assert create_response.status_code == 200
    invite = create_response.json()
    assert invite["code"] == "INVITE123"
    assert invite["is_active"] is True

    second_create_response = client.post(
        "/api/admin/invites",
        json={"code": "INVITE456"},
        headers=headers,
    )
    assert second_create_response.status_code == 200
    assert second_create_response.json()["code"] == "INVITE456"

    list_response = client.get("/api/admin/invites", headers=headers)

    assert list_response.status_code == 200
    assert [item["code"] for item in list_response.json()] == ["INVITE456", "INVITE123"]

    toggle_response = client.patch(f"/api/admin/invites/{invite['id']}/toggle", headers=headers)

    assert toggle_response.status_code == 200
    assert toggle_response.json()["is_active"] is False


def test_admin_can_batch_create_and_export_registration_invites(client):
    headers = _admin_auth_headers(client)

    batch_response = client.post(
        "/api/admin/invites/batch",
        json={"quantity": 10},
        headers=headers,
    )

    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert len(payload) == 10
    assert len({item["code"] for item in payload}) == 10
    assert all(item["is_active"] for item in payload)
    assert all(item["created_by_type"] == "admin" for item in payload)

    csv_response = client.get("/api/admin/invites/export?format=csv", headers=headers)
    txt_response = client.get("/api/admin/invites/export?format=txt", headers=headers)

    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "code,is_active,created_by_type,used_by_user_id,created_at" in csv_response.text
    assert payload[0]["code"] in csv_response.text

    assert txt_response.status_code == 200
    assert "text/plain" in txt_response.headers["content-type"]
    assert set(txt_response.text.strip().splitlines()) == {item["code"] for item in payload}


def test_admin_batch_registration_invites_rejects_unsupported_quantity(client):
    headers = _admin_auth_headers(client)

    response = client.post(
        "/api/admin/invites/batch",
        json={"quantity": 7},
        headers=headers,
    )

    assert response.status_code in {400, 422}
    assert "10" in str(response.json())


def test_admin_invite_list_includes_creator_and_used_user_identity(client):
    from app.database import SessionLocal
    from app.models.models import RegistrationInvite, User

    db = SessionLocal()
    try:
        inviter = User(
            username="alice",
            nickname="Alice Chen",
            access_link="http://testserver/access/alice-inviter",
            is_active=True,
            credit_balance=0,
        )
        used_user = User(
            username="bob",
            nickname="Bob Li",
            access_link="http://testserver/access/bob-used",
            is_active=True,
            credit_balance=0,
        )
        db.add_all([inviter, used_user])
        db.flush()
        db.add_all([
            RegistrationInvite(code="ADMIN-INVITE", is_active=True),
            RegistrationInvite(
                code="USER-INVITE",
                is_active=False,
                created_by_user_id=inviter.id,
                used_by_user_id=used_user.id,
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/invites", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    invites = {item["code"]: item for item in response.json()}
    assert invites["ADMIN-INVITE"]["created_by_type"] == "admin"
    assert invites["ADMIN-INVITE"]["created_by_display_name"] is None
    assert invites["USER-INVITE"]["created_by_type"] == "user"
    assert invites["USER-INVITE"]["created_by_username"] == "alice"
    assert invites["USER-INVITE"]["created_by_display_name"] == "Alice Chen"
    assert invites["USER-INVITE"]["used_by_username"] == "bob"
    assert invites["USER-INVITE"]["used_by_display_name"] == "Bob Li"


def test_admin_can_toggle_user_unlimited_flag(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
            is_unlimited=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    headers = _admin_auth_headers(client)
    response = client.patch(
        f"/api/admin/users/{user_id}/unlimited",
        json={"is_unlimited": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_unlimited"] is True

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        assert user.is_unlimited is True
    finally:
        db.close()


def test_server_mode_rejects_sample_placeholder_runtime_secrets(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "please-change-this-to-a-random-string-32-chars")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "please-change-this-password")

    with pytest.raises(RuntimeError):
        config_module.ensure_runtime_secrets_safe()


def test_server_mode_rejects_trivially_weak_custom_runtime_secrets(monkeypatch):
    monkeypatch.setattr(config_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "short")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "tiny")

    with pytest.raises(RuntimeError):
        config_module.ensure_runtime_secrets_safe()


def test_reload_settings_rejects_unsafe_server_secrets(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "SECRET_KEY=please-change-this-to-a-random-string-32-chars",
                "ADMIN_PASSWORD=please-change-this-password",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")

    with pytest.raises(RuntimeError):
        config_module.reload_settings()

    assert config_module.settings.APP_ENV == "development"
    assert config_module.settings.SECRET_KEY == "test-secret-key"
    assert config_module.settings.ADMIN_PASSWORD == "test-admin-password"


def test_env_file_path_prefers_runtime_override(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"

    monkeypatch.setenv("GANKAIGC_ENV_FILE", str(env_file))

    assert config_module.get_env_file_path() == str(env_file)


def test_admin_config_updates_runtime_env_file_from_override(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "SECRET_KEY=test-secret-key",
                "ADMIN_PASSWORD=test-admin-password",
                "POLISH_MODEL=old-model",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GANKAIGC_ENV_FILE", str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "old-model")
    admin_token = create_access_token({"sub": config_module.settings.ADMIN_USERNAME, "role": "admin"})

    response = client.post(
        "/api/admin/config",
        json={"POLISH_MODEL": "new-model"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert "POLISH_MODEL=new-model" in env_file.read_text(encoding="utf-8")
    assert config_module.settings.POLISH_MODEL == "new-model"


def test_admin_config_updates_model_provider_name(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "SECRET_KEY=test-secret-key",
                "ADMIN_PASSWORD=test-admin-password",
                "MODEL_PROVIDER_NAME=OpenAI Compatible 中转站",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "MODEL_PROVIDER_NAME", "OpenAI Compatible 中转站", raising=False)

    response = client.post(
        "/api/admin/config",
        json={"MODEL_PROVIDER_NAME": "Sub API 中转站"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert "MODEL_PROVIDER_NAME=Sub API 中转站" in env_file.read_text(encoding="utf-8")
    assert config_module.settings.MODEL_PROVIDER_NAME == "Sub API 中转站"

    config_response = client.get("/api/admin/config", headers=_admin_auth_headers(client))
    assert config_response.status_code == 200
    assert config_response.json()["system"]["model_provider_name"] == "Sub API 中转站"

    clear_response = client.post(
        "/api/admin/config",
        json={"MODEL_PROVIDER_NAME": ""},
        headers=_admin_auth_headers(client),
    )

    assert clear_response.status_code == 200
    assert "MODEL_PROVIDER_NAME=\n" in env_file.read_text(encoding="utf-8")
    assert config_module.settings.MODEL_PROVIDER_NAME == ""


def test_admin_config_creates_runtime_env_file_when_missing(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "old-model")

    response = client.post(
        "/api/admin/config",
        json={"POLISH_MODEL": "new-model"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert env_file.exists()
    assert env_file.read_text(encoding="utf-8") == "POLISH_MODEL=new-model\n"
    assert config_module.settings.POLISH_MODEL == "new-model"


def test_admin_config_save_keeps_compose_env_secrets_when_env_file_has_defaults(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "SECRET_KEY=your-secret-key-change-this-in-production",
                "ADMIN_USERNAME=admin",
                "ADMIN_PASSWORD=admin123",
                "POLISH_MODEL=old-model",
            ]
        ),
        encoding="utf-8",
    )
    docker_secret = "docker-compose-secret-key-32-chars"
    docker_admin_password = "docker-compose-admin-password"

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", docker_secret)
    monkeypatch.setattr(config_module.settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", docker_admin_password)
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "old-model")

    admin_token = create_access_token({"sub": "admin", "role": "admin"})
    response = client.post(
        "/api/admin/config",
        json={"POLISH_MODEL": "new-model"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert config_module.settings.POLISH_MODEL == "new-model"
    assert config_module.settings.SECRET_KEY == docker_secret
    assert config_module.settings.ADMIN_PASSWORD == docker_admin_password

    login_response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": docker_admin_password},
    )
    assert login_response.status_code == 200


def test_admin_config_does_not_return_full_model_api_keys(client, monkeypatch):
    api_keys = {
        "POLISH_API_KEY": "sk-polish-secret-123456",
        "ENHANCE_API_KEY": "sk-enhance-secret-abcdef",
        "EMOTION_API_KEY": "sk-emotion-secret-789012",
        "COMPRESSION_API_KEY": "sk-compression-secret-ghijkl",
    }
    for key, value in api_keys.items():
        monkeypatch.setattr(config_module.settings, key, value, raising=False)

    response = client.get("/api/admin/config", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    body = response.json()
    for section, full_key in (
        ("polish", api_keys["POLISH_API_KEY"]),
        ("enhance", api_keys["ENHANCE_API_KEY"]),
        ("emotion", api_keys["EMOTION_API_KEY"]),
        ("compression", api_keys["COMPRESSION_API_KEY"]),
    ):
        assert "api_key" not in body[section]
        assert body[section]["api_key_set"] is True
        assert body[section]["api_key_last4"] == full_key[-4:]
        assert full_key not in response.text


def test_admin_config_save_ignores_blank_model_api_key_updates(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "SECRET_KEY=test-secret-key",
                "ADMIN_PASSWORD=test-admin-password",
                "POLISH_MODEL=old-model",
                "POLISH_API_KEY=existing-secret-key",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "POLISH_MODEL", "old-model")
    monkeypatch.setattr(config_module.settings, "POLISH_API_KEY", "existing-secret-key")

    response = client.post(
        "/api/admin/config",
        json={"POLISH_MODEL": "new-model", "POLISH_API_KEY": "   "},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    env_content = env_file.read_text(encoding="utf-8")
    assert "POLISH_MODEL=new-model" in env_content
    assert "POLISH_API_KEY=existing-secret-key" in env_content
    assert config_module.settings.POLISH_MODEL == "new-model"
    assert config_module.settings.POLISH_API_KEY == "existing-secret-key"


def test_admin_config_rejects_private_model_base_url_update(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "POLISH_BASE_URL=https://api.openai.com/v1",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://api.openai.com/v1")

    response = client.post(
        "/api/admin/config",
        json={"POLISH_BASE_URL": "https://127.0.0.1/v1"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 400
    assert "Base URL" in response.json()["detail"]
    assert env_file.read_text(encoding="utf-8") == original_env
    assert config_module.settings.POLISH_BASE_URL == "https://api.openai.com/v1"


def test_admin_config_accepts_local_proxy_when_explicitly_enabled_on_local_host(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "SERVER_HOST=127.0.0.1",
            "ALLOW_LOCAL_MODEL_PROXY=true",
            "POLISH_BASE_URL=https://api.openai.com/v1",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://api.openai.com/v1")

    response = client.post(
        "/api/admin/config",
        json={"POLISH_BASE_URL": "http://127.0.0.1:8317/v1/"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert "POLISH_BASE_URL=http://127.0.0.1:8317/v1" in env_file.read_text(encoding="utf-8")
    assert config_module.settings.POLISH_BASE_URL == "http://127.0.0.1:8317/v1"


def test_admin_config_accepts_local_proxy_after_hot_reloading_server_host(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "SERVER_HOST=0.0.0.0",
            "ALLOW_LOCAL_MODEL_PROXY=false",
            "POLISH_BASE_URL=https://api.openai.com/v1",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "0.0.0.0", raising=False)
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", False, raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://api.openai.com/v1")

    response = client.post(
        "/api/admin/config",
        json={
            "SERVER_HOST": "127.0.0.1",
            "ALLOW_LOCAL_MODEL_PROXY": "true",
            "POLISH_BASE_URL": "http://127.0.0.1:8317/v1/",
        },
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    env_text = env_file.read_text(encoding="utf-8")
    assert "SERVER_HOST=127.0.0.1" in env_text
    assert "ALLOW_LOCAL_MODEL_PROXY=true" in env_text
    assert "POLISH_BASE_URL=http://127.0.0.1:8317/v1" in env_text
    assert config_module.settings.SERVER_HOST == "127.0.0.1"
    assert config_module.settings.ALLOW_LOCAL_MODEL_PROXY is True
    assert config_module.settings.POLISH_BASE_URL == "http://127.0.0.1:8317/v1"


def test_admin_config_rejects_local_proxy_when_server_host_is_exposed(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "SERVER_HOST=0.0.0.0",
            "ALLOW_LOCAL_MODEL_PROXY=true",
            "POLISH_BASE_URL=https://api.openai.com/v1",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "SERVER_HOST", "0.0.0.0", raising=False)
    monkeypatch.setattr(config_module.settings, "ALLOW_LOCAL_MODEL_PROXY", True, raising=False)
    monkeypatch.setattr(config_module.settings, "POLISH_BASE_URL", "https://api.openai.com/v1")

    response = client.post(
        "/api/admin/config",
        json={"POLISH_BASE_URL": "http://127.0.0.1:8317/v1"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 400
    assert "Base URL" in response.json()["detail"]
    assert env_file.read_text(encoding="utf-8") == original_env
    assert config_module.settings.POLISH_BASE_URL == "https://api.openai.com/v1"


def test_worker_healthcheck_is_disabled_in_docker_compose():
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    worker_section = compose_text.split("\n  worker:", 1)[1].split("\n  postgres:", 1)[0]

    assert "healthcheck:" in worker_section
    assert "disable: true" in worker_section


def test_docker_services_mount_env_docker_as_runtime_config():
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    app_section = compose_text.split("\n  app:", 1)[1].split("\n  worker:", 1)[0]
    worker_section = compose_text.split("\n  worker:", 1)[1].split("\n  postgres:", 1)[0]

    for section in (app_section, worker_section):
        assert "GANKAIGC_ENV_FILE: /app/config/.env.docker" in section
        assert "target: /app/config/.env.docker" in section

    assert "source: ./.env.docker" in app_section
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/backups" in app_section
    assert "source: ${GANKAIGC_HOST_PROJECT_DIR:-${PWD:-.}}/.env.docker" in worker_section


def test_dockerfile_creates_runtime_config_mount_directory():
    dockerfile = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert "mkdir -p /app/config" in dockerfile


def test_package_main_preserves_preconfigured_runtime_env_file():
    main_py = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")

    assert "os.environ.get('GANKAIGC_ENV_FILE') or os.path.join(APP_DIR, '.env')" in main_py
    assert "os.environ['GANKAIGC_ENV_FILE'] = ENV_FILE" in main_py


def test_worker_refreshes_runtime_config_file_during_loop():
    worker_py = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")

    assert "from app.config import reload_settings, settings" in worker_py
    assert "reload_settings()" in worker_py


def test_root_head_probe_is_supported(client):
    response = client.head("/")

    assert response.status_code == 200



def test_admin_config_updates_model_api_format(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "MODEL_API_FORMAT=openai_chat",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "MODEL_API_FORMAT", "openai_chat", raising=False)

    response = client.post(
        "/api/admin/config",
        json={"MODEL_API_FORMAT": "anthropic"},
        headers=_admin_auth_headers(client),
    )

    assert response.status_code == 200
    assert "MODEL_API_FORMAT=anthropic" in env_file.read_text(encoding="utf-8")
    assert config_module.settings.MODEL_API_FORMAT == "anthropic"

    get_response = client.get("/api/admin/config", headers=_admin_auth_headers(client))
    assert get_response.status_code == 200
    assert get_response.json()["system"]["model_api_format"] == "anthropic"

def test_admin_config_exposes_registration_enabled(client, monkeypatch):
    monkeypatch.setattr(config_module.settings, "REGISTRATION_ENABLED", False, raising=False)

    response = client.get("/api/admin/config", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    assert response.json()["system"]["registration_enabled"] is False


def test_admin_config_manages_document_parse_settings_without_leaking_mineru_token(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
            "MINERU_API_TOKEN=old-mineru-token",
            "PDF_STRUCTURE_ENGINE=mineru",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "MINERU_API_TOKEN", "old-mineru-token", raising=False)
    monkeypatch.setattr(config_module.settings, "PDF_STRUCTURE_ENGINE", "mineru", raising=False)

    get_response = client.get("/api/admin/config", headers=_admin_auth_headers(client))
    assert get_response.status_code == 200
    document_parse = get_response.json()["document_parse"]
    assert document_parse["mineru_api_token_set"] is True
    assert document_parse["mineru_api_token_last4"] == "oken"
    assert "old-mineru-token" not in str(document_parse)

    update_response = client.post(
        "/api/admin/config",
        json={
            "PDF_STRUCTURE_ENGINE": "markitdown",
            "MINERU_BASE_URL": "https://mineru.example",
            "MINERU_API_TOKEN": "",
            "MINERU_MODEL_VERSION": "vlm",
            "MINERU_ENABLE_FORMULA": "false",
            "MINERU_ENABLE_TABLE": "true",
            "MINERU_IS_OCR": "true",
            "MINERU_LANGUAGE": "ch",
            "MINERU_TIMEOUT_SECONDS": "180",
            "MINERU_POLL_INTERVAL_SECONDS": "1.5",
        },
        headers=_admin_auth_headers(client),
    )
    assert update_response.status_code == 200
    env_text = env_file.read_text(encoding="utf-8")
    assert "PDF_STRUCTURE_ENGINE=markitdown" in env_text
    assert "MINERU_BASE_URL=https://mineru.example" in env_text
    assert "MINERU_API_TOKEN=old-mineru-token" in env_text
    assert config_module.settings.PDF_STRUCTURE_ENGINE == "markitdown"
    assert config_module.settings.MINERU_API_TOKEN == "old-mineru-token"

    invalid_response = client.post(
        "/api/admin/config",
        json={"PDF_STRUCTURE_ENGINE": "docx_mineru"},
        headers=_admin_auth_headers(client),
    )
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == "PDF 解析引擎仅支持 mineru 或 markitdown"


def test_admin_database_manager_reports_read_only_and_sanitizes_records(client):
    from app.database import SessionLocal
    from app.models.models import OptimizationSession, User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            nickname="Alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.flush()
        db.add(
            OptimizationSession(
                user_id=user.id,
                session_id="secure-db-view",
                original_text="敏感论文原文",
                error_message="敏感错误堆栈",
                status="failed",
                processing_mode="paper_polish",
            )
        )
        db.commit()
    finally:
        db.close()

    headers = _admin_auth_headers(client)

    tables_response = client.get("/api/admin/database/tables", headers=headers)
    assert tables_response.status_code == 200
    assert tables_response.json()["can_write"] is False

    users_response = client.get("/api/admin/database/users", headers=headers)
    assert users_response.status_code == 200
    user_record = users_response.json()["items"][0]
    assert user_record["username"] == "alice"
    assert "password_hash" not in user_record

    sessions_response = client.get("/api/admin/database/optimization_sessions", headers=headers)
    assert sessions_response.status_code == 200
    session_record = sessions_response.json()["items"][0]
    assert session_record["session_id"] == "secure-db-view"
    assert "original_text" not in session_record
    assert "error_message" not in session_record


def test_admin_database_write_endpoints_are_disabled_by_default(client):
    from app.database import SessionLocal
    from app.models.models import User
    from app.utils.auth import get_password_hash

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            nickname="Alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    headers = _admin_auth_headers(client)

    update_response = client.put(
        f"/api/admin/database/users/{user_id}",
        json={"data": {"nickname": "Changed"}},
        headers=headers,
    )
    assert update_response.status_code == 403

    delete_response = client.delete(f"/api/admin/database/users/{user_id}", headers=headers)
    assert delete_response.status_code == 403

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        assert user.nickname == "Alice"
    finally:
        db.close()


def test_word_formatter_routes_are_not_mounted_when_disabled(client):
    usage_response = client.get("/api/word-formatter/usage")
    assert usage_response.status_code == 404

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    paths = openapi_response.json()["paths"]
    assert "/api/word-formatter/usage" not in paths
    assert "/api/word-formatter/specs/generate" not in paths


def test_admin_config_rollback_restores_env_file_and_live_settings_on_invalid_update(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env = "\n".join(
        [
            "APP_ENV=development",
            "SECRET_KEY=test-secret-key",
            "ADMIN_PASSWORD=test-admin-password",
        ]
    )
    env_file.write_text(original_env, encoding="utf-8")

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")

    response = client.post(
        "/api/admin/config",
        json={
            "APP_ENV": "production",
            "SECRET_KEY": "weak",
            "ADMIN_PASSWORD": "tiny",
        },
        headers=_admin_auth_headers(client),
    )

    assert response.status_code >= 400
    assert env_file.read_text(encoding="utf-8") == original_env
    assert config_module.settings.APP_ENV == "development"
    assert config_module.settings.SECRET_KEY == "test-secret-key"
    assert config_module.settings.ADMIN_PASSWORD == "test-admin-password"


def test_admin_config_rebuilds_active_cors_middleware(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "SECRET_KEY=test-secret-key",
                "ADMIN_PASSWORD=test-admin-password",
                "ALLOWED_ORIGINS=http://old.example",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(env_file))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(config_module.settings, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(config_module.settings, "ALLOWED_ORIGINS", "http://old.example")

    before = client.options(
        "/health",
        headers={
            "Origin": "http://new.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert before.status_code == 400

    response = client.post(
        "/api/admin/config",
        json={"ALLOWED_ORIGINS": "http://new.example"},
        headers=_admin_auth_headers(client),
    )
    assert response.status_code == 200

    after = client.options(
        "/health",
        headers={
            "Origin": "http://new.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert after.status_code == 200
    assert after.headers["access-control-allow-origin"] == "http://new.example"


def test_rate_limit_key_uses_direct_client_host(monkeypatch):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/login",
            "headers": [(b"x-forwarded-for", b"203.0.113.10")],
            "client": ("127.0.0.1", 4567),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
            "http_version": "1.1",
        }
    )

    assert _get_rate_limit_key(request, "auth") == "auth:127.0.0.1"


def test_legacy_admin_card_key_endpoints_are_removed(client):
    headers = _admin_auth_headers(client)

    legacy_requests = [
        ("post", "/api/admin/verify-card-key", {"json": {"card_key": "CARD123"}}),
        ("post", "/api/admin/card-keys", {"json": {"card_key": "CARD123"}, "headers": headers}),
        ("post", "/api/admin/batch-generate-keys?count=1", {"headers": headers}),
        ("post", f"/api/admin/generate-keys?admin_password={config_module.settings.ADMIN_PASSWORD}", {"json": {"count": 1}}),
    ]

    for method, path, kwargs in legacy_requests:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404


def test_admin_session_lists_include_user_identity(client):
    from app.database import SessionLocal
    from app.models.models import OptimizationSession, User

    db = SessionLocal()
    try:
        user = User(
            username="alice",
            nickname="Alice Chen",
            access_link="http://testserver/access/alice",
        )
        db.add(user)
        db.flush()
        db.add_all([
            OptimizationSession(
                user_id=user.id,
                session_id="session-history",
                original_text="历史会话文本",
                status="completed",
                processing_mode="paper_polish_enhance",
                total_segments=1,
            ),
            OptimizationSession(
                user_id=user.id,
                session_id="session-active",
                original_text="实时会话文本",
                status="processing",
                processing_mode="paper_polish",
                total_segments=1,
            ),
        ])
        db.commit()
    finally:
        db.close()

    headers = _admin_auth_headers(client)

    history_response = client.get("/api/admin/sessions", params={"status": "completed"}, headers=headers)
    assert history_response.status_code == 200
    history_session = history_response.json()[0]
    assert history_session["username"] == "alice"
    assert history_session["nickname"] == "Alice Chen"
    assert history_session["user_display_name"] == "Alice Chen"

    active_response = client.get("/api/admin/sessions/active", headers=headers)
    assert active_response.status_code == 200
    active_session = active_response.json()[0]
    assert active_session["username"] == "alice"
    assert active_session["nickname"] == "Alice Chen"
    assert active_session["user_display_name"] == "Alice Chen"


def test_admin_statistics_count_all_processing_modes(client):
    from app.database import SessionLocal
    from app.models.models import OptimizationSession, User
    from app.utils.time import utcnow

    db = SessionLocal()
    now = utcnow()
    try:
        user = User(
            username="mode_owner",
            nickname="Mode Owner",
            access_link="http://testserver/access/mode-owner",
        )
        db.add(user)
        db.flush()
        for mode in ("paper_polish", "paper_enhance", "paper_polish_enhance", "emotion_polish"):
            db.add(
                OptimizationSession(
                    user_id=user.id,
                    session_id=f"stats-{mode}",
                    original_text="统计模式文本",
                    status="completed",
                    processing_mode=mode,
                    total_segments=1,
                    created_at=now,
                    completed_at=now + timedelta(seconds=10),
                )
            )
        db.commit()
    finally:
        db.close()

    headers = _admin_auth_headers(client)
    response = client.get("/api/admin/statistics", headers=headers)

    assert response.status_code == 200
    processing = response.json()["processing"]
    assert processing["paper_polish_count"] == 1
    assert processing["paper_enhance_count"] == 1
    assert processing["paper_polish_enhance_count"] == 1
    assert processing["emotion_polish_count"] == 1
    assert {row["id"] for row in processing["mode_rows"]} >= {
        "paper_polish",
        "paper_enhance",
        "paper_polish_enhance",
        "emotion_polish",
        "ai_detect_reduce",
    }


def test_admin_statistics_honors_date_range_filter_and_returns_real_series(client):
    from app.database import SessionLocal
    from app.models.models import OptimizationSegment, OptimizationSession, User
    from app.utils.time import utcnow

    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_time = max(today_start, now - timedelta(seconds=1))
    eight_days_ago = today_start - timedelta(days=8)
    twenty_days_ago = today_start - timedelta(days=20)

    db = SessionLocal()
    try:
        user = User(
            username="range_owner",
            nickname="Range Owner",
            access_link="http://testserver/access/range-owner",
            last_used=today_time,
        )
        db.add(user)
        db.flush()

        sessions = [
            OptimizationSession(
                user_id=user.id,
                session_id="stats-today",
                original_text="今日真实统计文本" * 2,
                status="completed",
                processing_mode="paper_polish",
                total_segments=1,
                created_at=today_time,
                completed_at=today_time + timedelta(seconds=30),
            ),
            OptimizationSession(
                user_id=user.id,
                session_id="stats-eight-days-ago",
                original_text="八天前真实统计文本",
                status="completed",
                processing_mode="paper_enhance",
                total_segments=1,
                created_at=eight_days_ago,
                completed_at=eight_days_ago + timedelta(seconds=45),
            ),
            OptimizationSession(
                user_id=user.id,
                session_id="stats-twenty-days-ago",
                original_text="二十天前真实统计文本",
                status="failed",
                processing_mode="emotion_polish",
                total_segments=1,
                created_at=twenty_days_ago,
            ),
        ]
        db.add_all(sessions)
        db.flush()
        for session in sessions:
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=0,
                    stage="polish",
                    original_text=session.original_text,
                    status="completed" if session.status == "completed" else "failed",
                )
            )
        db.commit()
    finally:
        db.close()

    headers = _admin_auth_headers(client)
    today_response = client.get("/api/admin/statistics", params={"range": "today"}, headers=headers)
    seven_day_response = client.get("/api/admin/statistics", params={"range": "7d"}, headers=headers)
    thirty_day_response = client.get("/api/admin/statistics", params={"range": "30d"}, headers=headers)

    assert today_response.status_code == 200
    assert seven_day_response.status_code == 200
    assert thirty_day_response.status_code == 200

    today_stats = today_response.json()
    seven_day_stats = seven_day_response.json()
    thirty_day_stats = thirty_day_response.json()

    assert today_stats["range"]["key"] == "today"
    assert seven_day_stats["range"]["key"] == "7d"
    assert thirty_day_stats["range"]["key"] == "30d"
    assert today_stats["sessions"]["in_range"] == 1
    assert seven_day_stats["sessions"]["in_range"] == 1
    assert thirty_day_stats["sessions"]["in_range"] == 3
    assert today_stats["sessions"]["completed_in_range"] == 1
    assert thirty_day_stats["sessions"]["completed_in_range"] == 2
    assert today_stats["requests"]["in_range"] == 1
    assert thirty_day_stats["requests"]["in_range"] == 3
    assert today_stats["processing"]["total_chars_processed_in_range"] == len("今日真实统计文本" * 2)
    assert thirty_day_stats["processing"]["mode_total_in_range"] == 2
    assert "trend_percent" in seven_day_stats["sessions"]
    assert "success_rate_trend_percent" in seven_day_stats["sessions"]
    assert set(seven_day_stats["processing"]["series"]) >= {
        "sessions",
        "active_users",
        "completed_sessions",
        "success_rate",
        "chars_processed",
        "avg_processing_time",
        "avg_input_chars",
    }
    assert len(today_stats["processing"]["series"]["sessions"]) >= 1
    assert len(seven_day_stats["processing"]["series"]["sessions"]) == 7
    assert len(thirty_day_stats["processing"]["series"]["sessions"]) == 30
    assert all("trend_percent" in row and "series" in row for row in thirty_day_stats["processing"]["mode_rows"])


def test_admin_statistics_omits_word_formatter_when_feature_disabled(client):
    response = client.get("/api/admin/statistics", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    assert "word_formatter" not in response.json()


def test_crypto_helpers_round_trip_with_test_fernet_key(monkeypatch):
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())

    encrypted = encrypt_secret("top-secret")

    assert encrypted != "top-secret"
    assert decrypt_secret(encrypted) == "top-secret"
