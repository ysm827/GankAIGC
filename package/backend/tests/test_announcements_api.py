import app.config as config_module
from app.database import SessionLocal
from app.models.models import User
from app.utils.auth import create_user_access_token, get_password_hash


def _admin_auth_headers(client):
    response = client.post(
        "/api/admin/login",
        json={"username": config_module.settings.ADMIN_USERNAME, "password": config_module.settings.ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_user(username="announcement-user"):
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=get_password_hash("Password123!"),
            access_link=f"http://testserver/access/{username}",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _user_auth_headers(user_id, username="announcement-user"):
    return {"Authorization": f"Bearer {create_user_access_token(user_id, username)}"}


def test_admin_can_create_and_list_announcements(client):
    headers = _admin_auth_headers(client)

    response = client.post(
        "/api/admin/announcements",
        json={
            "title": "维护通知",
            "content": "今晚 23:00 到 23:10 进行维护",
            "category": "maintenance",
            "is_active": True,
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "维护通知"
    assert payload["content"] == "今晚 23:00 到 23:10 进行维护"
    assert payload["category"] == "maintenance"
    assert payload["is_active"] is True

    list_response = client.get("/api/admin/announcements", headers=headers)

    assert list_response.status_code == 200
    assert [item["title"] for item in list_response.json()] == ["维护通知"]


def test_user_only_sees_active_announcements_newest_first(client):
    admin_headers = _admin_auth_headers(client)
    user_id = _create_user()
    user_headers = _user_auth_headers(user_id)

    inactive_response = client.post(
        "/api/admin/announcements",
        json={"title": "旧公告", "content": "不要显示", "category": "notice", "is_active": False},
        headers=admin_headers,
    )
    active_response = client.post(
        "/api/admin/announcements",
        json={"title": "模型切换", "content": "已切换新模型", "category": "model", "is_active": True},
        headers=admin_headers,
    )

    assert inactive_response.status_code == 200
    assert active_response.status_code == 200

    response = client.get("/api/user/announcements", headers=user_headers)

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload] == ["模型切换"]
    assert payload[0]["category"] == "model"


def test_admin_can_disable_announcement_so_users_no_longer_see_it(client):
    admin_headers = _admin_auth_headers(client)
    user_id = _create_user()
    user_headers = _user_auth_headers(user_id)
    create_response = client.post(
        "/api/admin/announcements",
        json={"title": "使用说明", "content": "新手请先配置 API", "category": "guide", "is_active": True},
        headers=admin_headers,
    )
    announcement_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/admin/announcements/{announcement_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    user_response = client.get("/api/user/announcements", headers=user_headers)

    assert patch_response.status_code == 200
    assert patch_response.json()["is_active"] is False
    assert user_response.status_code == 200
    assert user_response.json() == []
