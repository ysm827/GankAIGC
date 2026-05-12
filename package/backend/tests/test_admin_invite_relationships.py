import app.config as config_module
from app.database import SessionLocal
from app.models.models import RegistrationInvite, User
from app.utils.auth import get_password_hash


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


def _create_user(db, username):
    user = User(
        username=username,
        nickname=username.title(),
        password_hash=get_password_hash("Password123!"),
        access_link=f"http://testserver/access/{username}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def test_admin_invite_relationships_show_admin_and_user_invites(client):
    db = SessionLocal()
    try:
        inviter = _create_user(db, "alice")
        invitee = _create_user(db, "bob")
        admin_invitee = _create_user(db, "carol")
        db.add_all(
            [
                RegistrationInvite(code="ADMIN-USED", is_active=False, used_by_user_id=admin_invitee.id),
                RegistrationInvite(code="USER-USED", is_active=False, created_by_user_id=inviter.id, used_by_user_id=invitee.id),
                RegistrationInvite(code="USER-OPEN", is_active=True, created_by_user_id=inviter.id),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/invites/relationships", headers=_admin_auth_headers(client))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {
        "total": 3,
        "admin_created": 1,
        "user_created": 2,
        "used": 2,
        "unused": 1,
    }
    rows = {row["code"]: row for row in data["items"]}
    assert rows["ADMIN-USED"]["inviter_type"] == "admin"
    assert rows["ADMIN-USED"]["inviter_display_name"] == "管理员"
    assert rows["ADMIN-USED"]["invitee_display_name"] == "Carol"
    assert rows["USER-USED"]["inviter_type"] == "user"
    assert rows["USER-USED"]["inviter_display_name"] == "Alice"
    assert rows["USER-USED"]["invitee_display_name"] == "Bob"
    assert rows["USER-OPEN"]["status_label"] == "未使用"
