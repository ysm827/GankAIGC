import socket
import sys
import types

import app.config as config_module
from app.database import SessionLocal
from app.models.models import CreditTransaction, OptimizationSession, User
from app.utils.auth import create_user_access_token, get_password_hash, verify_stream_token


class NoRunBackgroundTasks:
    def add_task(self, *args, **kwargs):
        return None


async def _noop_run_optimization(*args, **kwargs):
    return None


class ReadyZhuqueService:
    async def readiness(self, text=None):
        return {
            "ready": True,
            "connected": True,
            "page_found": True,
            "has_token": True,
            "remaining_uses": 20,
            "button_enabled": True,
            "text_length": len(text or ""),
            "text_length_ok": True,
            "estimated_first_round_credits": 10,
            "estimated_max_round_credits": 50,
            "message": "朱雀已就绪",
            "actions": [],
        }


def _allow_public_model_url_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )


def _create_user(credit_balance=0, is_unlimited=False):
    db = SessionLocal()
    try:
        user = User(
            username="alice",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/alice",
            is_active=True,
            credit_balance=credit_balance,
            is_unlimited=is_unlimited,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_user_access_token(user.id, user.username)
        return user.id, token
    finally:
        db.close()


def test_calculate_optimization_credits_uses_billable_characters_and_stage_multiplier():
    from app.services.credit_service import calculate_optimization_credits, count_billable_characters

    assert count_billable_characters("a b\nc") == 3
    assert calculate_optimization_credits("短文本", "paper_enhance") == 1
    assert calculate_optimization_credits("汉" * 1000, "paper_enhance") == 1
    assert calculate_optimization_credits("汉" * 1001, "paper_enhance") == 2
    assert calculate_optimization_credits("汉" * 3000, "paper_polish_enhance") == 6


def test_parse_markdown_document_upload_returns_editable_text(client):
    _, token = _create_user(credit_balance=0)

    response = client.post(
        "/api/optimization/documents/parse",
        files={"file": ("paper.md", b"# Title\n\nMarkdown body", "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "paper.md"
    assert payload["parser"] == "markdown"
    assert payload["text"] == "# Title\n\nMarkdown body"
    assert payload["char_count"] > 0


def test_parse_docx_document_upload_uses_markitdown(client, monkeypatch):
    _, token = _create_user(credit_balance=0)
    seen_extensions = []

    class FakeMarkItDown:
        def __init__(self, enable_plugins=False):
            assert enable_plugins is False

        def convert_stream(self, stream, *, file_extension=None):
            seen_extensions.append(file_extension)
            assert stream.read().startswith(b"PK\x03\x04")
            return types.SimpleNamespace(text_content="# 论文标题\n\n解析正文")

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    response = client.post(
        "/api/optimization/documents/parse",
        files={
            "file": (
                "paper.docx",
                b"PK\x03\x04 fake docx content",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert seen_extensions == [".docx"]
    assert payload["filename"] == "paper.docx"
    assert payload["parser"] == "markitdown"
    assert payload["text"] == "# 论文标题\n\n解析正文"
    assert payload["char_count"] == 8


def test_parse_document_upload_rejects_pdf_for_now(client):
    _, token = _create_user(credit_balance=0)

    response = client.post(
        "/api/optimization/documents/parse",
        files={"file": ("paper.pdf", b"%PDF-1.7", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Word(.docx) 和 Markdown" in response.json()["detail"]


def test_platform_mode_holds_character_based_credits_before_processing(client, monkeypatch):
    from app.routes import optimization

    user_id, token = _create_user(credit_balance=8)
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "汉" * 3000,
            "processing_mode": "paper_polish_enhance",
            "billing_mode": "platform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["charge_status"] == "held"
    assert response.json()["charged_credits"] == 6

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        session = db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).one()
        transaction = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).one()
        assert user.credit_balance == 2
        assert session.billing_mode == "platform"
        assert transaction.delta == -6
        assert transaction.reason == "optimization_start"
    finally:
        db.close()


def test_byok_mode_does_not_consume_credits(client, monkeypatch):
    from app.routes import optimization

    user_id, token = _create_user(credit_balance=0)
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)
    _allow_public_model_url_dns(monkeypatch)

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "test paragraph",
            "processing_mode": "paper_polish",
            "billing_mode": "byok",
            "polish_config": {
                "model": "gpt-5.4",
                "api_key": "sk-test",
                "base_url": "https://api.example/v1",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["charge_status"] == "not_charged"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()
        assert user.credit_balance == 0
        assert transactions == []
    finally:
        db.close()


def test_byok_mode_rejects_private_request_base_url(client, monkeypatch):
    from app.routes import optimization

    _, token = _create_user(credit_balance=0)
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "test paragraph",
            "processing_mode": "paper_polish",
            "billing_mode": "byok",
            "polish_config": {
                "model": "gpt-5.4",
                "api_key": "sk-test",
                "base_url": "https://127.0.0.1/v1",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "Base URL" in response.json()["detail"]


def test_platform_mode_rejects_user_with_insufficient_credits(client, monkeypatch):
    from app.routes import optimization

    _, token = _create_user(credit_balance=5)
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "汉" * 3000,
            "processing_mode": "paper_polish_enhance",
            "billing_mode": "platform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "平台剩余啤酒不足，本次需要 6 啤酒，当前剩余 5 啤酒"


def test_ai_detect_reduce_start_does_not_hold_platform_credit(client, monkeypatch):
    from app.routes import optimization

    user_id, token = _create_user(credit_balance=0)
    monkeypatch.setattr(optimization, "BackgroundTasks", NoRunBackgroundTasks)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)
    monkeypatch.setattr(optimization, "zhuque_service", ReadyZhuqueService())

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "汉" * 1000,
            "processing_mode": "ai_detect_reduce",
            "billing_mode": "platform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["processing_mode"] == "ai_detect_reduce"
    assert response.json()["current_stage"] == "ai_detect_reduce"
    assert response.json()["charge_status"] == "not_charged"
    assert response.json()["charged_credits"] == 0

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()
        assert user.credit_balance == 0
        assert transactions == []
    finally:
        db.close()


def test_ai_detect_reduce_retry_does_not_hold_platform_credit(client, monkeypatch):
    from app.routes import optimization

    user_id, token = _create_user(credit_balance=0)
    monkeypatch.setattr(optimization, "run_optimization", _noop_run_optimization)

    db = SessionLocal()
    try:
        failed_session = OptimizationSession(
            user_id=user_id,
            session_id="failed-ai-detect-reduce-no-prehold",
            original_text="汉" * 1000,
            current_stage="ai_detect_reduce",
            status="failed",
            error_message="朱雀降重未达标",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            charged_credits=0,
        )
        db.add(failed_session)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/optimization/sessions/failed-ai-detect-reduce-no-prehold/retry",
        json={"billing_mode": "keep"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        session = db.query(OptimizationSession).filter(
            OptimizationSession.session_id == "failed-ai-detect-reduce-no-prehold"
        ).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()
        assert user.credit_balance == 0
        assert session.status == "queued"
        assert session.billing_mode == "platform"
        assert session.charge_status == "not_charged"
        assert session.charged_credits == 0
        assert transactions == []
    finally:
        db.close()


def test_session_stream_uses_short_lived_stream_token_instead_of_login_token(client):
    user_id, token = _create_user(credit_balance=0)
    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="stream-token-session",
            original_text="测试正文",
            current_stage="polish",
            status="queued",
            progress=0,
            processing_mode="paper_polish",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.commit()
    finally:
        db.close()

    progress_with_query_login_token = client.get(
        "/api/optimization/sessions/stream-token-session/progress",
        params={"access_token": token},
    )
    assert progress_with_query_login_token.status_code == 401

    stream_with_query_login_token = client.get(
        "/api/optimization/sessions/stream-token-session/stream",
        params={"access_token": token},
    )
    assert stream_with_query_login_token.status_code == 401

    token_response = client.post(
        "/api/optimization/sessions/stream-token-session/stream-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert token_response.status_code == 200
    body = token_response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == config_module.settings.STREAM_TOKEN_EXPIRE_SECONDS
    assert body["stream_token"]
    assert body["stream_token"] != token

    payload = verify_stream_token(body["stream_token"])
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "stream"
    assert payload["scope"] == "session_stream"
    assert payload["session_id"] == "stream-token-session"
    assert payload["token_version"] == 0

    stream_with_login_token_in_stream_param = client.get(
        "/api/optimization/sessions/stream-token-session/stream",
        params={"stream_token": token},
    )
    assert stream_with_login_token_in_stream_param.status_code == 401


def test_credit_service_public_error_messages_use_beer_unit():
    from fastapi import HTTPException
    from app.services.credit_service import CreditService

    user_id, _ = _create_user(credit_balance=0)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        service = CreditService(db)

        error_checks = [
            (lambda: service.hold_platform_credit(user, reason="test", amount=0), "扣除啤酒必须大于 0"),
            (lambda: service.refund_platform_credit(user, reason="test", amount=0), "退回啤酒必须大于 0"),
            (lambda: service.add_credits(user, amount=0, reason="test"), "充值啤酒必须大于 0"),
        ]

        for action, expected_detail in error_checks:
            try:
                action()
            except HTTPException as exc:
                assert exc.detail == expected_detail
            else:
                raise AssertionError("expected HTTPException")
    finally:
        db.close()


def test_failed_platform_job_refunds_held_credits_once():
    from app.services.credit_service import CreditService

    user_id, _ = _create_user(credit_balance=5)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        session = OptimizationSession(
            user_id=user.id,
            session_id="session-1",
            original_text="test paragraph",
            current_stage="polish",
            status="queued",
            billing_mode="platform",
            charge_status="held",
            charged_credits=3,
        )
        db.add(session)
        db.flush()
        CreditService(db).hold_platform_credit(user, reason="optimization_start", session_id=session.id, amount=3)
        db.commit()

        CreditService(db).refund_held_platform_credit(session)
        db.commit()
        CreditService(db).refund_held_platform_credit(session)
        db.commit()

        db.refresh(user)
        assert user.credit_balance == 5
        assert session.charge_status == "refunded"
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user.id).all()
        assert [txn.delta for txn in transactions] == [-3, 3]
    finally:
        db.close()
