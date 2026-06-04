import asyncio
import json
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models.models import CreditTransaction, OptimizationSegment, OptimizationSession, User
from app.services.optimization_service import OptimizationService
from app.utils.auth import create_user_access_token, get_password_hash


class FakeZhuqueService:
    def __init__(self, rates):
        self.rates = list(rates)
        self.detected_texts = []
        self.start_calls = 0

    async def start(self):
        self.start_calls += 1

    async def detect(self, text):
        self.detected_texts.append(text)
        next_result = self.rates.pop(0)
        if isinstance(next_result, dict):
            result = dict(next_result)
            result.setdefault("success", True)
            result.setdefault("remaining_uses", 99)
            result.setdefault("text_length", len(text))
            return result

        rate = next_result
        return {
            "success": True,
            "rate": rate,
            "labels_ratio": {"0": max(0, 1 - rate / 100), "1": rate / 100, "2": 0.0},
            "remaining_uses": 99,
            "text_length": len(text),
        }


class FailingZhuqueService:
    def __init__(self, message):
        self.message = message
        self.start_calls = 0
        self.detected_texts = []

    async def start(self):
        self.start_calls += 1

    async def detect(self, text):
        self.detected_texts.append(text)
        return {
            "success": False,
            "message": self.message,
            "rate": 0,
            "rate_label": "",
            "labels_ratio": {},
            "alert_text": "",
            "alert_title": "",
            "remaining_uses": -1,
            "text_length": len(text),
        }


class UnavailableZhuqueService:
    def __init__(self, port=9223):
        self.start_calls = 0
        self.detect_calls = 0
        self.port = port

    async def start(self):
        self.start_calls += 1
        raise RuntimeError(f"无法连接Chrome CDP端口 {self.port}。请确保Chrome以 --remote-debugging-port={self.port} 启动")

    async def detect(self, text):
        self.detect_calls += 1
        raise AssertionError("detect should not run when Zhuque preflight fails")


class StatusOnlyZhuqueAPI:
    def __init__(self, status_payload):
        self.status_payload = status_payload
        self.status_calls = 0

    async def status(self):
        self.status_calls += 1
        return dict(self.status_payload)

    async def detect(self, text, timeout=60.0):
        return {
            "success": True,
            "rate": 0,
            "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
            "remaining_uses": 4,
            "text_length": len(text),
        }


class FakeAIService:
    def __init__(self):
        self.polish_calls = []
        self.enhance_calls = []

    async def polish_text(self, text, prompt, history=None, stream=False):
        self.polish_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        return f"润色后:{text}"

    async def enhance_text(self, text, prompt, history=None, stream=False):
        self.enhance_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        return f"增强后:{text}"

    async def generate(self, prompt):
        raise AssertionError("ai_detect_reduce must reuse polish_text + enhance_text, not a separate reduce prompt")


def _install_fake_ai_services(service, fake_ai):
    service.polish_service = fake_ai
    service.enhance_service = fake_ai


def _joined_segment_starts(segment_texts):
    starts = []
    cursor = 0
    for text in segment_texts:
        starts.append(cursor)
        cursor += len(text) + 2
    return starts


def _create_user(*, credit_balance=20, zhuque_free_uses_remaining=20):
    db = SessionLocal()
    try:
        user = User(
            username="zhuque-user",
            password_hash=get_password_hash("Password123!"),
            access_link="http://testserver/access/zhuque-user",
            is_active=True,
            credit_balance=credit_balance,
            zhuque_free_uses_remaining=zhuque_free_uses_remaining,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def test_launch_zhuque_chrome_uses_configured_port_and_profile(monkeypatch, tmp_path):
    from app.services import zhuque_browser_launcher

    chrome_path = tmp_path / "chrome.exe"
    chrome_path.write_text("", encoding="utf-8")
    popen_calls = []

    class FakePopen:
        def __init__(self, args, stdout=None, stderr=None):
            popen_calls.append({"args": args, "stdout": stdout, "stderr": stderr})

    monkeypatch.setattr(zhuque_browser_launcher, "find_chrome_executable", lambda: str(chrome_path))
    monkeypatch.setattr(zhuque_browser_launcher, "get_zhuque_user_data_dir", lambda port: str(tmp_path / f"profile-{port}"))
    monkeypatch.setattr(zhuque_browser_launcher.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(zhuque_browser_launcher.settings, "ZHUQUE_CDP_PORT", 9333, raising=False)

    result = zhuque_browser_launcher.launch_zhuque_chrome()

    assert result["status"] == "started"
    assert result["port"] == 9333
    assert result["url"] == zhuque_browser_launcher.ZHUQUE_DETECT_URL
    assert Path(result["user_data_dir"]).name == "profile-9333"
    assert popen_calls
    args = popen_calls[0]["args"]
    assert args[0] == str(chrome_path)
    assert "--remote-debugging-port=9333" in args
    assert f"--user-data-dir={result['user_data_dir']}" in args
    assert zhuque_browser_launcher.ZHUQUE_DETECT_URL in args


def test_launch_zhuque_chrome_reports_missing_chrome(monkeypatch):
    from app.services import zhuque_browser_launcher

    monkeypatch.setattr(zhuque_browser_launcher, "find_chrome_executable", lambda: None)

    with pytest.raises(RuntimeError, match="未找到 Chrome"):
        zhuque_browser_launcher.launch_zhuque_chrome()


def test_zhuque_api_parses_websocket_success_frame():
    from app.services.zhuque_api import parse_zhuque_websocket_result

    payload = json.dumps(
        {
            "status": "success",
            "confidence": 1.0,
            "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
            "segment_labels": [
                {
                    "text": "检测文本",
                    "label": 1,
                    "conf": 0.9979,
                    "order": 1,
                    "position": [0, 4],
                }
            ],
            "content_type": 0,
            "availableUses": 18,
            "feedback_token": "token",
        },
        ensure_ascii=False,
    )

    result = parse_zhuque_websocket_result(payload, text_length=738)

    assert result == {
        "success": True,
        "rate": 100.0,
        "risk_rate": 100.0,
        "rate_label": "WebSocket检测结果",
        "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
        "alert_text": "未发现明显的人工创作特征",
        "alert_title": "",
        "message": "",
        "remaining_uses": 18,
        "text_length": 738,
        "confidence": 1.0,
        "segment_labels": [
            {
                "text": "检测文本",
                "label": 1,
                "conf": 0.9979,
                "order": 1,
                "position": [0, 4],
            }
        ],
        "content_type": 0,
        "feedback_token": "token",
        "source": "websocket",
    }


def test_zhuque_api_treats_websocket_label_zero_as_human():
    from app.services.zhuque_api import parse_zhuque_websocket_result

    payload = json.dumps(
        {
            "status": "success",
            "confidence": 0.0,
            "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
            "availableUses": 18,
        },
        ensure_ascii=False,
    )

    result = parse_zhuque_websocket_result(payload, text_length=738)

    assert result["rate"] == 0.0
    assert result["alert_text"] == "人工创作特征较明显"


def test_zhuque_api_ignores_non_terminal_websocket_frames():
    from app.services.zhuque_api import parse_zhuque_websocket_result

    assert parse_zhuque_websocket_result("not-json", text_length=1000) is None
    assert parse_zhuque_websocket_result('{"status":"waiting","remaining":0}', text_length=1000) is None
    assert parse_zhuque_websocket_result('{"code":"1","msg":"OK"}', text_length=1000) is None


def test_zhuque_api_classify_uses_websocket_label_mapping():
    from app.services.zhuque_api import ZhuqueAPI

    async def classify_with(raw_result):
        api = ZhuqueAPI()

        async def fake_detect(text):
            return raw_result

        api.detect = fake_detect
        return await api.classify("测试文本" * 200)

    ai_result = asyncio.run(
        classify_with(
            {
                "success": True,
                "rate": 100.0,
                "alert_text": "",
                "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
            }
        )
    )
    human_result = asyncio.run(
        classify_with(
            {
                "success": True,
                "rate": 0.0,
                "alert_text": "",
                "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
            }
        )
    )

    assert ai_result["verdict"] == "AI_generated"
    assert ai_result["verdict_label"] == "AI生成"
    assert human_result["verdict"] == "human_written"
    assert human_result["verdict_label"] == "人工编写"


def test_zhuque_browser_start_endpoint_launches_local_chrome(client, monkeypatch, tmp_path):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    user_data_dir = str(tmp_path / "profile")

    monkeypatch.setattr(
        optimization_route,
        "launch_zhuque_chrome",
        lambda: {
            "status": "started",
            "port": 9333,
            "url": "https://matrix.tencent.com/ai-detect/",
            "user_data_dir": user_data_dir,
        },
    )

    response = client.post(
        "/api/optimization/zhuque/browser/start",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "started",
        "port": 9333,
        "url": "https://matrix.tencent.com/ai-detect/",
        "user_data_dir": user_data_dir,
    }


def test_zhuque_browser_status_endpoint_reports_live_cdp(client, monkeypatch):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")

    monkeypatch.setattr(
        optimization_route,
        "get_zhuque_browser_status",
        lambda: {
            "status": "connected",
            "connected": True,
            "port": 9333,
            "url": "https://matrix.tencent.com/ai-detect/",
            "message": "Chrome CDP 已连接",
        },
    )

    response = client.get(
        "/api/optimization/zhuque/browser/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["status"] == "connected"
    assert response.json()["port"] == 9333


def test_zhuque_browser_status_endpoint_reports_closed_cdp(client, monkeypatch):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")

    monkeypatch.setattr(
        optimization_route,
        "get_zhuque_browser_status",
        lambda: {
            "status": "disconnected",
            "connected": False,
            "port": 9333,
            "url": "https://matrix.tencent.com/ai-detect/",
            "message": "未连接到 Chrome CDP 端口 9333",
        },
    )

    response = client.get(
        "/api/optimization/zhuque/browser/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["status"] == "disconnected"
    assert "9333" in response.json()["message"]


def test_zhuque_service_allows_anonymous_page_with_remaining_free_uses(monkeypatch):
    from app.services.zhuque_service import ZhuqueService
    import app.services.zhuque_service as zhuque_service_module

    fake_api = StatusOnlyZhuqueAPI(
        {
            "url": "https://matrix.tencent.com/ai-detect/",
            "has_token": False,
            "remaining_uses": 5,
            "btn_text": "立即检测(今日剩余5次)",
        }
    )
    service = ZhuqueService()
    service.api = None
    service._ready = False
    service._consumer_task = None
    monkeypatch.setattr(zhuque_service_module, "ZhuqueAPI", lambda cdp_port, debug=False: fake_api)
    monkeypatch.setattr(zhuque_service_module.settings, "ZHUQUE_CDP_PORT", 9333, raising=False)

    try:
        asyncio.run(service.start())

        assert service.is_ready is True
        assert fake_api.status_calls == 1
    finally:
        if service._consumer_task:
            service._consumer_task.cancel()
        service._ready = False
        service.api = None
        service._consumer_task = None


def test_session_detail_includes_zhuque_report_payload(client):
    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    report = {
        "success": True,
        "rate": 18.5,
        "labels_ratio": {"human": 0.815, "ai": 0.185},
        "remaining_uses": 17,
        "text_length": 732,
        "message": "检测完成",
    }

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-detail-report",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="completed",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            progress=100,
        )
        db.add(session)
        db.flush()
        db.add(
            OptimizationSegment(
                session_id=session.id,
                segment_index=0,
                stage="enhance",
                original_text="待检测文本" * 80,
                polished_text="润色后文本",
                enhanced_text="增强后文本",
                status="completed",
                zhuque_detect_rate=18.5,
                zhuque_detect_result=json.dumps(report, ensure_ascii=False),
                zhuque_detect_count=2,
                zhuque_reduce_attempt=1,
                zhuque_reduced_text="增强后文本",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/optimization/sessions/zhuque-detail-report",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    segment = response.json()["segments"][0]
    assert segment["zhuque_detect_result"] == json.dumps(report, ensure_ascii=False)


def test_ai_detect_reduce_fails_when_zhuque_rejects_any_segment(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    fake_zhuque = FailingZhuqueService("文本长度不足 (164<350字), 请提供更长的文本")
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, FakeAIService()))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-detect-rejected",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="太短文本" * 20,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match="文本长度不足"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()

        assert session.status == "failed"
        assert "文本长度不足" in session.error_message
        assert segment.zhuque_detect_count == 1
        assert segment.zhuque_detect_rate is None
        assert segment.zhuque_reduce_attempt == 0
        assert user.credit_balance == 20
        assert transactions == []
    finally:
        db.close()


def test_ai_detect_reduce_rewrites_segments_above_threshold_and_records_results(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([80, 12])
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    fake_ai = FakeAIService()
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-session",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="待检测文本" * 80,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()

        assert session.status == "completed"
        assert segment.zhuque_detect_count == 2
        assert segment.zhuque_reduce_attempt == 1
        assert segment.polished_text == f"润色后:{segment.original_text}"
        assert segment.enhanced_text == f"增强后:{segment.polished_text}"
        assert segment.zhuque_reduced_text == segment.enhanced_text
        assert segment.zhuque_detect_rate == 12
        assert user.zhuque_free_uses_remaining == 20
        assert user.zhuque_total_uses == 0
        assert user.credit_balance == 10
        assert [(txn.reason, txn.delta) for txn in transactions] == [("zhuque_reduce", -10)]
        assert fake_zhuque.detected_texts[0] == segment.original_text
        assert fake_zhuque.detected_texts[1] == segment.zhuque_reduced_text
        assert [call["text"] for call in fake_ai.polish_calls] == [segment.original_text]
        assert [call["text"] for call in fake_ai.enhance_calls] == [segment.polished_text]
    finally:
        db.close()


def test_ai_detect_reduce_rewrites_only_segments_marked_ai_by_zhuque_labels(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_ai = FakeAIService()
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    segment_texts = ["短段甲" * 60, "短段乙" * 60, "短段丙" * 60, "短段丁" * 60]
    joined_text = "\n\n".join(segment_texts)
    segment_starts = _joined_segment_starts(segment_texts)

    fake_zhuque = FakeZhuqueService(
        [
            {
                "success": True,
                "rate": 80,
                "labels_ratio": {"0": 0.2, "1": 0.8, "2": 0.0},
                "segment_labels": [
                    {
                        "text": segment_texts[1],
                        "label": 1,
                        "conf": 0.99,
                        "order": 1,
                        "position": [
                            segment_starts[1],
                            segment_starts[1] + len(segment_texts[1]),
                        ],
                    },
                    {
                        "text": segment_texts[3],
                        "label": 1,
                        "conf": 0.98,
                        "order": 2,
                        "position": [
                            segment_starts[3],
                            segment_starts[3] + len(segment_texts[3]),
                        ],
                    },
                ],
            },
            12,
        ]
    )
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-full-text-detect",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        for index, text in enumerate(segment_texts):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()

        assert session.status == "completed"
        assert fake_zhuque.detected_texts[0] == joined_text
        assert fake_zhuque.detected_texts[1] == "\n\n".join(
            seg.zhuque_reduced_text or seg.original_text for seg in segments
        )
        assert [seg.zhuque_detect_rate for seg in segments] == [12, 12, 12, 12]
        assert [seg.zhuque_detect_count for seg in segments] == [2, 2, 2, 2]
        assert [seg.zhuque_reduce_attempt for seg in segments] == [0, 1, 0, 1]
        assert [seg.polished_text for seg in segments] == [
            None,
            f"润色后:{segment_texts[1]}",
            None,
            f"润色后:{segment_texts[3]}",
        ]
        assert [seg.enhanced_text for seg in segments] == [
            None,
            f"增强后:润色后:{segment_texts[1]}",
            None,
            f"增强后:润色后:{segment_texts[3]}",
        ]
        assert [seg.zhuque_reduced_text for seg in segments] == [
            None,
            segments[1].enhanced_text,
            None,
            segments[3].enhanced_text,
        ]
        assert [call["text"] for call in fake_ai.polish_calls] == [segment_texts[1], segment_texts[3]]
        assert [call["text"] for call in fake_ai.enhance_calls] == [
            segments[1].polished_text,
            segments[3].polished_text,
        ]
        assert user.credit_balance == 30
        assert [(txn.reason, txn.delta) for txn in transactions] == [
            ("zhuque_reduce", -10),
            ("zhuque_reduce", -10),
        ]
    finally:
        db.close()


def test_ai_detect_reduce_treats_suspicious_ratio_as_over_threshold(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService(
        [
            {
                "success": True,
                "rate": 0.0,
                "labels_ratio": {"0": 0.275, "1": 0.0, "2": 0.725},
                "segment_labels": [],
                "remaining_uses": 99,
            }
        ]
    )
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-suspicious-over-threshold",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="疑似AI文本" * 80,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match="72.5"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        assert session.status == "failed"
        assert segment.zhuque_detect_rate == 72.5
        assert fake_ai.polish_calls == []
        assert fake_ai.enhance_calls == []
    finally:
        db.close()


def test_ai_detect_reduce_rewrites_suspicious_segments_but_keeps_human_segments(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_ai = FakeAIService()
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    segment_texts = ["疑似段甲" * 50, "疑似段乙" * 50, "人工段丙" * 50]
    segment_starts = _joined_segment_starts(segment_texts)
    fake_zhuque = FakeZhuqueService(
        [
            {
                "success": True,
                "rate": 0.0,
                "labels_ratio": {"0": 0.275, "1": 0.0, "2": 0.725},
                "segment_labels": [
                    {
                        "text": segment_texts[0],
                        "label": 2,
                        "conf": 0.95,
                        "order": 1,
                        "position": [segment_starts[0], segment_starts[0] + len(segment_texts[0])],
                    },
                    {
                        "text": segment_texts[1],
                        "label": 2,
                        "conf": 0.94,
                        "order": 2,
                        "position": [segment_starts[1], segment_starts[1] + len(segment_texts[1])],
                    },
                    {
                        "text": segment_texts[2],
                        "label": 0,
                        "conf": 0.99,
                        "order": 3,
                        "position": [segment_starts[2], segment_starts[2] + len(segment_texts[2])],
                    },
                ],
            },
            10,
        ]
    )
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-suspicious-only-selected",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        for index, text in enumerate(segment_texts):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )
        user = db.query(User).filter(User.id == user_id).one()

        assert session.status == "completed"
        assert [seg.zhuque_reduce_attempt for seg in segments] == [1, 1, 0]
        assert [seg.zhuque_reduced_text for seg in segments] == [
            segments[0].enhanced_text,
            segments[1].enhanced_text,
            None,
        ]
        assert [call["text"] for call in fake_ai.polish_calls] == segment_texts[:2]
        assert user.credit_balance == 30
    finally:
        db.close()


def test_ai_detect_reduce_rewrites_all_segments_when_zhuque_has_no_segment_labels(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([80, 12])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    segment_texts = ["无标签短段甲" * 40, "无标签短段乙" * 40]

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-fallback-all-segments",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        for index, text in enumerate(segment_texts):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )

        assert session.status == "completed"
        assert [seg.zhuque_reduce_attempt for seg in segments] == [1, 1]
        assert [call["text"] for call in fake_ai.polish_calls] == segment_texts
        assert [call["text"] for call in fake_ai.enhance_calls] == [seg.polished_text for seg in segments]
    finally:
        db.close()


def test_ai_detect_reduce_leaves_original_segments_when_full_text_is_below_threshold(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([10])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    segment_texts = ["人工短段甲" * 20, "人工短段乙" * 20]

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-full-text-low-ai",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        for index, text in enumerate(segment_texts):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )
        user = db.query(User).filter(User.id == user_id).one()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()

        assert session.status == "completed"
        assert fake_zhuque.detected_texts == ["\n\n".join(segment_texts)]
        assert [seg.zhuque_detect_rate for seg in segments] == [10, 10]
        assert [seg.zhuque_reduce_attempt for seg in segments] == [0, 0]
        assert [seg.zhuque_reduced_text for seg in segments] == [None, None]
        assert fake_ai.polish_calls == []
        assert fake_ai.enhance_calls == []
        assert user.credit_balance == 50
        assert transactions == []
    finally:
        db.close()


def test_ai_detect_reduce_fails_when_rate_stays_above_threshold_after_max_rounds(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 100])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-still-high-after-max-rounds",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="高AI文本" * 80,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match="仍高于阈值"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        assert session.status == "failed"
        assert "100" in session.error_message
        assert segment.zhuque_detect_rate == 100
        assert segment.zhuque_detect_count == 2
        assert segment.zhuque_reduce_attempt == 1
        assert segment.polished_text == f"润色后:{segment.original_text}"
        assert segment.enhanced_text == f"增强后:{segment.polished_text}"
        assert segment.zhuque_reduced_text == segment.enhanced_text
    finally:
        db.close()


def test_ai_detect_reduce_retry_continues_from_latest_reduced_text(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=50, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([80, 10])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    original_text = "原始高AI文本" * 80
    latest_reduced_text = "上一轮最新降重文本" * 40

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-retry-from-latest-reduced",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="enhance",
            original_text=original_text,
            polished_text="上一轮润色文本",
            enhanced_text=latest_reduced_text,
            zhuque_reduced_text=latest_reduced_text,
            zhuque_reduce_attempt=5,
            status="failed",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        assert session.status == "completed"
        assert fake_zhuque.detected_texts[0] == latest_reduced_text
        assert fake_ai.polish_calls[0]["text"] == latest_reduced_text
        assert segment.zhuque_reduce_attempt == 6
        assert segment.polished_text == f"润色后:{latest_reduced_text}"
        assert segment.enhanced_text == f"增强后:{segment.polished_text}"
        assert segment.zhuque_reduced_text == segment.enhanced_text
        assert fake_zhuque.detected_texts[1] == segment.zhuque_reduced_text
    finally:
        db.close()


def test_ai_detect_reduce_retry_failure_reports_cumulative_rounds(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([95, 90, 85, 80, 75, 70])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    original_text = "原始高AI文本" * 80
    latest_reduced_text = "失败任务最新降重文本" * 40

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-retry-cumulative-failure",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="enhance",
            original_text=original_text,
            polished_text="上一轮润色文本",
            enhanced_text=latest_reduced_text,
            zhuque_reduced_text=latest_reduced_text,
            zhuque_reduce_attempt=5,
            status="failed",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)

        with pytest.raises(RuntimeError, match="累计 10 轮"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        assert session.status == "failed"
        assert "本次已完成 5 轮" in session.error_message
        assert "累计 10 轮" in session.error_message
        assert fake_zhuque.detected_texts[0] == latest_reduced_text
        assert fake_ai.polish_calls[0]["text"] == latest_reduced_text
        assert segment.zhuque_reduce_attempt == 10
        assert fake_zhuque.detected_texts[-1] == segment.zhuque_reduced_text
    finally:
        db.close()


def test_ai_detect_reduce_escalates_humanize_strategy_when_rate_does_not_drop(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 100, 100, 10])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 3, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-evolution-strategy",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="深度学习模型在医学影像分割任务中保持Dice系数稳定。" * 30,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        assert session.status == "completed"
        assert segment.zhuque_reduce_attempt == 3
        assert len(fake_ai.polish_calls) == 3
        assert "策略：轻度自然化" in fake_ai.polish_calls[0]["prompt"]
        assert "策略：句式重组" in fake_ai.polish_calls[1]["prompt"]
        assert "策略：强结构重写" in fake_ai.polish_calls[2]["prompt"]
        assert "必须保留专业术语" in fake_ai.polish_calls[2]["prompt"]
        assert "不得改变原文意思" in fake_ai.enhance_calls[2]["prompt"]
    finally:
        db.close()


def test_ai_detect_reduce_preflights_zhuque_before_segment_loop(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    configured_port = 9333
    fake_zhuque = UnavailableZhuqueService(port=configured_port)
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)

    init_calls = []
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: init_calls.append(self.session_obj.session_id))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_CDP_PORT", configured_port, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-preflight-fails",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
        )
        db.add(session)
        db.flush()
        for index in range(2):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=f"待检测文本{index}" * 50,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match=f"Chrome CDP端口 {configured_port}"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        assert fake_zhuque.start_calls == 1
        assert fake_zhuque.detect_calls == 0
        assert init_calls == []
        assert session.status == "failed"
        assert f"Chrome {configured_port}" in session.error_message
        assert "--remote-debugging-port=9333" in session.error_message
        assert "启动朱雀浏览器" in session.error_message
    finally:
        db.close()
