import asyncio
import json
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models.models import CreditTransaction, OptimizationSegment, OptimizationSession, User, ZhuquePromptMemory
from app.services.ai_service import count_text_length
from app.services.optimization_service import OptimizationService
from app.utils.auth import create_user_access_token, get_password_hash


class FakeZhuqueService:
    def __init__(self, rates):
        self.rates = list(rates)
        self.detected_texts = []
        self.start_calls = 0
        self.readiness_calls = []

    async def start(self):
        self.start_calls += 1

    async def readiness(self, text=None):
        self.readiness_calls.append(text)
        return {
            "ready": True,
            "connected": True,
            "page_found": True,
            "has_token": True,
            "remaining_uses": 99,
            "button_enabled": True,
            "text_length": len(text or ""),
            "text_length_ok": len(text or "") >= 350 if text is not None else True,
            "estimated_first_round_credits": 10,
            "estimated_max_round_credits": 50,
            "message": "朱雀已就绪",
            "actions": [],
        }

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
            "labels_ratio": {"0": rate / 100, "1": max(0, 1 - rate / 100), "2": 0.0},
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
        raise RuntimeError("未找到朱雀微信登录凭证，请先微信扫码授权")

    async def readiness(self, text=None):
        return {
            "ready": False,
            "connected": False,
            "page_found": False,
            "has_token": False,
            "remaining_uses": -1,
            "button_enabled": False,
            "text_length": len(text or ""),
            "text_length_ok": len(text or "") >= 350 if text is not None else True,
            "estimated_first_round_credits": 0,
            "estimated_max_round_credits": 0,
            "message": "未找到朱雀微信登录凭证",
            "actions": ["微信扫码登录朱雀"],
        }

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

    def credential_status(self):
        self.status_calls += 1
        return dict(self.status_payload)

    async def detect(self, text, timeout=60.0):
        return {
            "success": True,
            "rate": 0,
            "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
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
        if "rewrite_mode: paper_reconstruction" in prompt:
            return json.dumps(
                {
                    "candidates": [
                        {"id": "A", "text": text.replace("具有重要支撑", "提供参考")},
                        {"id": "B", "text": text.replace("进一步为临床辅助诊断提供重要支撑", "可作为临床辅助诊断的参考")},
                        {"id": "C", "text": text.replace("有效提升", "改善").replace("重要支撑", "参考")},
                    ]
                },
                ensure_ascii=False,
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


class BloatedThenLengthRepairAIService(FakeAIService):
    def __init__(self, repaired_text):
        super().__init__()
        self.repaired_text = repaired_text

    async def polish_text(self, text, prompt, history=None, stream=False):
        self.polish_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        return text

    async def enhance_text(self, text, prompt, history=None, stream=False):
        self.enhance_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        if "朱雀长度校正" in prompt:
            return self.repaired_text
        return f"{text}{'额外解释' * 80}"


class PlateauRecoveryAIService(FakeAIService):
    async def polish_text(self, text, prompt, history=None, stream=False):
        self.polish_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        if "卡点候选B" in prompt:
            return f"自动探索B:{text}"
        if "卡点候选C" in prompt:
            return f"自动探索C:{text}"
        if "卡点候选A" in prompt:
            return f"自动探索A:{text}"
        if "逐段候选S2" in prompt:
            return f"局部探索S2:{text}"
        if "逐段候选S1" in prompt:
            return f"局部探索S1:{text}"
        return f"常规:{text}"

    async def enhance_text(self, text, prompt, history=None, stream=False):
        self.enhance_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        return text


class DeepReconstructionAIService(PlateauRecoveryAIService):
    async def polish_text(self, text, prompt, history=None, stream=False):
        self.polish_calls.append(
            {
                "text": text,
                "prompt": prompt,
                "history": list(history or []),
                "stream": stream,
            }
        )
        if "深度重构路线:evidence_first" in prompt:
            return f"深度重构证据优先:{text}"
        if "深度重构路线:method_first" in prompt:
            return f"深度重构方法优先:{text}"
        if "深度重构路线:constraint_first" in prompt:
            return f"深度重构限定优先:{text}"
        return await super().polish_text(text, prompt, history=history, stream=stream)


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


def test_zhuque_wechat_capture_launches_capture_script(monkeypatch, tmp_path):
    import app.routes.optimization as optimization_route

    script_path = tmp_path / "capture_zhuque_creds.py"
    script_path.write_text("print('capture')", encoding="utf-8")
    popen_calls = []

    class FakePopen:
        def __init__(self, args, cwd=None, env=None, stdout=None, stderr=None, start_new_session=None):
            popen_calls.append(
                {
                    "args": args,
                    "cwd": cwd,
                    "env": env,
                    "stdout": stdout,
                    "stderr": stderr,
                    "start_new_session": start_new_session,
                }
            )

    class FakeAPI:
        def credential_status(self):
            return {
                "ready": False,
                "credential_file": str(script_path.parent / "creds_latest.json"),
            }

    class FakeZhuqueService:
        def _ensure_api(self):
            return FakeAPI()

    monkeypatch.setattr(optimization_route, "zhuque_service", FakeZhuqueService())
    monkeypatch.setattr(optimization_route, "_zhuque_capture_script_path", lambda: script_path)
    monkeypatch.setattr(optimization_route.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(optimization_route, "_zhuque_playwright_browser_ready", lambda: True)
    monkeypatch.setattr(optimization_route.subprocess, "Popen", FakePopen)

    result = optimization_route._start_zhuque_wechat_capture()

    assert result["status"] == "started"
    assert result["auth_mode"] == "headless_api"
    assert result["login_mode"] == "wechat_qr"
    assert result["credential_file"].endswith("creds_latest.json")
    assert "无头 API" in result["message"]
    assert popen_calls
    assert popen_calls[0]["args"] == [optimization_route.sys.executable, str(script_path)]
    assert popen_calls[0]["cwd"] == str(script_path.parent)
    assert "PLAYWRIGHT_BROWSERS_PATH" in popen_calls[0]["env"]
    assert popen_calls[0]["start_new_session"] is True


def test_zhuque_wechat_capture_reports_missing_playwright(monkeypatch, tmp_path):
    import app.routes.optimization as optimization_route

    script_path = tmp_path / "capture_zhuque_creds.py"
    script_path.write_text("print('capture')", encoding="utf-8")

    class FakeAPI:
        def credential_status(self):
            return {
                "ready": False,
                "credential_file": str(script_path.parent / "creds_latest.json"),
            }

    class FakeZhuqueService:
        def _ensure_api(self):
            return FakeAPI()

    monkeypatch.setattr(optimization_route, "zhuque_service", FakeZhuqueService())
    monkeypatch.setattr(optimization_route, "_zhuque_capture_script_path", lambda: script_path)
    monkeypatch.setattr(optimization_route.importlib.util, "find_spec", lambda name: None)

    result = optimization_route._start_zhuque_wechat_capture()

    assert result["status"] == "manual_required"
    assert "pip install playwright" in result["command"]
    assert "扫码授权页" in result["message"]


def test_zhuque_wechat_capture_reports_missing_playwright_browser(monkeypatch, tmp_path):
    import app.routes.optimization as optimization_route

    script_path = tmp_path / "capture_zhuque_creds.py"
    script_path.write_text("print('capture')", encoding="utf-8")

    class FakeAPI:
        def credential_status(self):
            return {
                "ready": False,
                "credential_file": str(script_path.parent / "creds_latest.json"),
            }

    class FakeZhuqueService:
        def _ensure_api(self):
            return FakeAPI()

    monkeypatch.setattr(optimization_route, "zhuque_service", FakeZhuqueService())
    monkeypatch.setattr(optimization_route, "_zhuque_capture_script_path", lambda: script_path)
    monkeypatch.setattr(optimization_route.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(optimization_route, "_zhuque_playwright_browser_ready", lambda: False)

    result = optimization_route._start_zhuque_wechat_capture()

    assert result["status"] == "manual_required"
    assert "playwright install chromium" in result["command"]
    assert "无头 API" in result["message"]


def test_zhuque_api_parses_websocket_success_frame():
    from app.services.zhuque_api import parse_zhuque_websocket_result

    payload = json.dumps(
        {
            "status": "success",
            "confidence": 1.0,
            "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
            "segment_labels": [
                {
                    "text": "检测文本",
                    "label": 0,
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
        "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
        "alert_text": "未发现明显的人工创作特征",
        "alert_title": "",
        "message": "",
        "remaining_uses": 18,
        "text_length": 738,
        "confidence": 1.0,
        "segment_labels": [
            {
                "text": "检测文本",
                "label": 0,
                "conf": 0.9979,
                "order": 1,
                "position": [0, 4],
            }
        ],
        "content_type": 0,
        "feedback_token": "token",
        "source": "websocket",
    }


def test_zhuque_api_parses_remaining_uses_from_button_text():
    from app.services.zhuque_api import normalize_zhuque_result

    result = normalize_zhuque_result(
        {
            "confidence": 0,
            "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
            "button_text": "Detect now(18 left)",
        },
        text_length=738,
        source="page_fallback",
    )

    assert result["remaining_uses"] == 18


def test_zhuque_api_credential_status_parses_remaining_uses_field(tmp_path):
    from app.services.zhuque_api import ZhuqueAPI

    creds_file = tmp_path / "creds_latest.json"
    creds_file.write_text(
        json.dumps(
            {
                "access_token": "token",
                "fp": "fp",
                "userName": "tester",
                "quotaText": "",
                "remainingUses": 17,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    status = ZhuqueAPI(credentials_file=creds_file).credential_status()

    assert status["ready"] is True
    assert status["remaining_uses"] == 17


def test_zhuque_api_treats_websocket_label_one_as_human():
    from app.services.zhuque_api import parse_zhuque_websocket_result

    payload = json.dumps(
        {
            "status": "success",
            "confidence": 0.0,
            "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
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
                "labels_ratio": {"0": 1.0, "1": 0.0, "2": 0.0},
            }
        )
    )
    human_result = asyncio.run(
        classify_with(
            {
                "success": True,
                "rate": 0.0,
                "alert_text": "",
                "labels_ratio": {"0": 0.0, "1": 1.0, "2": 0.0},
            }
        )
    )

    assert ai_result["verdict"] == "AI_generated"
    assert ai_result["verdict_label"] == "AI生成"
    assert human_result["verdict"] == "human_written"
    assert human_result["verdict_label"] == "人工编写"


def test_zhuque_browser_start_endpoint_starts_wechat_capture(client, monkeypatch, tmp_path):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    credential_file = str(tmp_path / "creds_latest.json")

    monkeypatch.setattr(
        optimization_route,
        "_start_zhuque_wechat_capture",
        lambda: {
            "status": "started",
            "auth_mode": "headless_api",
            "login_mode": "wechat_qr",
            "credential_file": credential_file,
            "command": "python zhuque_pkg/capture_zhuque_creds.py",
            "message": "已打开朱雀微信扫码授权页；扫码完成后检测走无头 API",
        },
    )

    response = client.post(
        "/api/optimization/zhuque/browser/start",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "started",
        "auth_mode": "headless_api",
        "login_mode": "wechat_qr",
        "credential_file": credential_file,
        "command": "python zhuque_pkg/capture_zhuque_creds.py",
        "message": "已打开朱雀微信扫码授权页；扫码完成后检测走无头 API",
    }


def test_zhuque_browser_status_endpoint_reports_ready_credentials(client, monkeypatch):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")

    class FakeAPI:
        def credential_status(self):
            return {
                "ready": True,
                "connected": True,
                "has_token": True,
                "credential_file": "/tmp/creds_latest.json",
                "user_name": "tester",
                "quota_text": "今日剩余 18 次",
                "captured_at": "2026-06-16T00:00:00Z",
                "message": "朱雀微信凭证已就绪，检测将走无头 API",
            }

    class FakeZhuqueService:
        def _ensure_api(self):
            return FakeAPI()

    monkeypatch.setattr(optimization_route, "zhuque_service", FakeZhuqueService())

    response = client.get(
        "/api/optimization/zhuque/browser/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["ready"] is True
    assert body["status"] == "connected"
    assert body["auth_mode"] == "headless_api"
    assert body["login_mode"] == "wechat_qr"
    assert body["credential_file"] == "/tmp/creds_latest.json"
    assert body["user_name"] == "tester"


def test_zhuque_browser_status_endpoint_reports_missing_credentials(client, monkeypatch):
    import app.routes.optimization as optimization_route

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")

    class FakeAPI:
        def credential_status(self):
            return {
                "ready": False,
                "connected": False,
                "has_token": False,
                "credential_file": "/tmp/creds_latest.json",
                "message": "未找到朱雀微信登录凭证",
            }

    class FakeZhuqueService:
        def _ensure_api(self):
            return FakeAPI()

    monkeypatch.setattr(optimization_route, "zhuque_service", FakeZhuqueService())

    response = client.get(
        "/api/optimization/zhuque/browser/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["ready"] is False
    assert body["status"] == "missing_credentials"
    assert "微信登录凭证" in body["message"]


def test_zhuque_service_starts_with_wechat_credentials(monkeypatch):
    from app.services.zhuque_service import ZhuqueService
    import app.services.zhuque_service as zhuque_service_module

    fake_api = StatusOnlyZhuqueAPI(
        {
            "ready": True,
            "connected": True,
            "page_found": True,
            "has_token": True,
            "remaining_uses": 5,
            "credential_file": "/tmp/creds_latest.json",
            "message": "朱雀微信凭证已就绪，检测将走无头 API",
        }
    )
    service = ZhuqueService()
    service.api = None
    service._ready = False
    service._consumer_task = None
    monkeypatch.setattr(zhuque_service_module, "ZhuqueAPI", lambda *args, **kwargs: fake_api)

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


def test_zhuque_service_readiness_reports_credential_state_and_text_length(monkeypatch):
    from app.services.zhuque_service import ZhuqueService
    import app.services.zhuque_service as zhuque_service_module

    fake_api = StatusOnlyZhuqueAPI(
        {
            "ready": True,
            "connected": True,
            "page_found": True,
            "has_token": True,
            "remaining_uses": 3,
            "button_enabled": True,
            "credential_file": "/tmp/creds_latest.json",
            "message": "朱雀微信凭证已就绪，检测将走无头 API",
        }
    )
    service = ZhuqueService()
    service.api = None
    service._ready = False
    service._consumer_task = None
    monkeypatch.setattr(zhuque_service_module, "ZhuqueAPI", lambda *args, **kwargs: fake_api)

    try:
        result = asyncio.run(service.readiness("短文本"))

        assert result["connected"] is True
        assert result["page_found"] is True
        assert result["has_token"] is True
        assert result["remaining_uses"] == 3
        assert result["button_enabled"] is True
        assert result["text_length"] == 3
        assert result["text_length_ok"] is False
        assert result["ready"] is False
        assert "350" in result["message"]
        assert "补充文本到 350 字以上" in result["actions"]
    finally:
        if service._consumer_task:
            service._consumer_task.cancel()
        service._ready = False
        service.api = None
        service._consumer_task = None


def test_zhuque_service_readiness_uses_live_quota_probe(monkeypatch):
    from app.services.zhuque_service import ZhuqueService
    import app.services.zhuque_service as zhuque_service_module

    class FakeAPI(StatusOnlyZhuqueAPI):
        async def peek_remaining_uses(self, timeout=3.0):
            return 16

    fake_api = FakeAPI(
        {
            "ready": True,
            "connected": True,
            "page_found": True,
            "has_token": True,
            "remaining_uses": -1,
            "button_enabled": True,
            "credential_file": "/tmp/creds_latest.json",
            "message": "朱雀微信凭证已就绪，检测将走无头 API",
        }
    )
    service = ZhuqueService()
    service.api = None
    service._ready = False
    service._consumer_task = None
    service._last_remaining_uses = None
    monkeypatch.setattr(zhuque_service_module, "ZhuqueAPI", lambda *args, **kwargs: fake_api)

    try:
        result = asyncio.run(service.readiness("汉" * 500))

        assert result["remaining_uses"] == 16
        assert result["ready"] is True
    finally:
        if service._consumer_task:
            service._consumer_task.cancel()
        service._ready = False
        service.api = None
        service._consumer_task = None
        service._last_remaining_uses = None


def test_zhuque_readiness_endpoint_returns_actionable_state(client, monkeypatch):
    from app.routes import optimization

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")

    class FakeReadyService:
        async def readiness(self, text=None):
            return {
                "ready": False,
                "connected": True,
                "page_found": True,
                "has_token": False,
                "remaining_uses": 0,
                "button_enabled": False,
                "text_length": len(text or ""),
                "text_length_ok": True,
                "estimated_first_round_credits": 0,
                "estimated_max_round_credits": 0,
                "message": "朱雀次数不足，请登录或切换账号",
                "actions": ["登录或切换朱雀账号"],
            }

    monkeypatch.setattr(optimization, "zhuque_service", FakeReadyService())

    response = client.get(
        "/api/optimization/zhuque/readiness",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["connected"] is True
    assert body["remaining_uses"] == 0
    assert "登录或切换朱雀账号" in body["actions"]


def test_ai_detect_reduce_start_rejects_short_text_before_creating_session(client, monkeypatch):
    from app.routes import optimization

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    monkeypatch.setattr(optimization.settings, "INLINE_TASK_WORKER_ENABLED", False, raising=False)

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "短文本",
            "processing_mode": "ai_detect_reduce",
            "billing_mode": "platform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "350" in response.json()["detail"]

    db = SessionLocal()
    try:
        sessions = db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).all()
        transactions = db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).all()
        assert sessions == []
        assert transactions == []
    finally:
        db.close()


def test_ai_detect_reduce_start_rejects_unready_zhuque_before_creating_session(client, monkeypatch):
    from app.routes import optimization

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    monkeypatch.setattr(optimization.settings, "INLINE_TASK_WORKER_ENABLED", False, raising=False)

    class FakeUnreadyService:
        async def readiness(self, text=None):
            return {
                "ready": False,
                "connected": False,
                "page_found": False,
                "has_token": False,
                "remaining_uses": -1,
                "button_enabled": False,
                "text_length": len(text or ""),
                "text_length_ok": True,
                "estimated_first_round_credits": 10,
                "estimated_max_round_credits": 50,
                "message": "未找到朱雀微信登录凭证",
                "actions": ["微信扫码登录朱雀"],
            }

    monkeypatch.setattr(optimization, "zhuque_service", FakeUnreadyService())

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "汉" * 500,
            "processing_mode": "ai_detect_reduce",
            "billing_mode": "platform",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert "未找到朱雀微信登录凭证" in response.json()["detail"]
    assert "微信扫码登录朱雀" in response.json()["detail"]

    db = SessionLocal()
    try:
        assert db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).count() == 0
        assert db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).count() == 0
    finally:
        db.close()


def test_ai_detect_reduce_byok_requires_provider_before_zhuque_preflight(client, monkeypatch):
    from app.routes import optimization

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    readiness_calls = []

    class FakeReadyService:
        async def readiness(self, text=None):
            readiness_calls.append(text)
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

    monkeypatch.setattr(optimization, "zhuque_service", FakeReadyService())

    response = client.post(
        "/api/optimization/start",
        json={
            "original_text": "汉" * 500,
            "processing_mode": "ai_detect_reduce",
            "billing_mode": "byok",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先保存自带 API 配置"
    assert readiness_calls == []

    db = SessionLocal()
    try:
        assert db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).count() == 0
    finally:
        db.close()


def test_zhuque_preflight_byok_requires_provider_before_readiness(client, monkeypatch):
    from app.routes import optimization

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    token = create_user_access_token(user_id, "zhuque-user")
    readiness_calls = []

    class FakeReadyService:
        async def readiness(self, text=None):
            readiness_calls.append(text)
            return {"ready": True, "connected": True, "page_found": True, "has_token": True, "remaining_uses": 20, "button_enabled": True, "text_length": len(text or ""), "text_length_ok": True, "estimated_first_round_credits": 10, "estimated_max_round_credits": 50, "message": "朱雀已就绪", "actions": []}

    monkeypatch.setattr(optimization, "zhuque_service", FakeReadyService())

    response = client.post(
        "/api/optimization/zhuque/preflight",
        json={
            "original_text": "汉" * 500,
            "processing_mode": "ai_detect_reduce",
            "billing_mode": "byok",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先保存自带 API 配置"
    assert readiness_calls == []


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
    assert "zhuque_agent_trace" in response.json()
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
        trace = json.loads(session.zhuque_agent_trace)
        assert trace["version"] == 1
        assert trace["threshold"] == 20.0
        assert trace["events"][0]["type"] == "detect"
        assert trace["events"][0]["rate"] == 80
        assert trace["events"][1]["type"] == "reduce"
        assert trace["events"][1]["round"] == 1
        assert trace["events"][1]["strategy"] == "轻度自然化"
        assert trace["events"][1]["selected_segment_indices"] == [0]
        assert trace["events"][1]["old_rate"] == 80
        assert trace["events"][1]["new_rate"] == 12
        assert trace["final"]["status"] == "completed"
        assert trace["final"]["rate"] == 12
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


def test_ai_detect_reduce_repairs_bloated_output_to_within_ten_percent(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([80, 0])
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    original_text = (
        "革命纪念馆展陈更新中，变化最先出现在展品位置和参观路线。"
        "观众的叙事线索、互动方式以及交流节奏也会随着展示空间变化。"
    ) * 4
    repaired_text = original_text.replace("最先出现在展品位置和参观路线", "首先体现在展品位置、参观路线", 1)
    fake_ai = BloatedThenLengthRepairAIService(repaired_text)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-length-guard",
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
            original_text=original_text,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)
        original_length = count_text_length(original_text)
        reduced_length = count_text_length(segment.zhuque_reduced_text)

        assert session.status == "completed"
        assert reduced_length <= int(original_length * 1.1)
        assert reduced_length >= int(original_length * 0.9)
        assert segment.zhuque_reduced_text == repaired_text
        assert segment.enhanced_text == repaired_text
        assert len(fake_ai.enhance_calls) == 2
        assert "朱雀长度校正" in fake_ai.enhance_calls[1]["prompt"]
        assert fake_zhuque.detected_texts[1] == repaired_text
    finally:
        db.close()


def test_ai_detect_reduce_length_repair_uses_original_segment_length_on_retry(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([80, 0])
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 1, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    original_text = (
        "革命纪念馆展陈更新中，数字展示会改变观众的参观路线。"
        "后续研究仍需要结合现场反馈来判断展示效果。"
    ) * 4
    previous_bloated_text = f"{original_text}{'额外解释' * 90}"
    repaired_text = original_text.replace("改变观众的参观路线", "影响观众参观路线", 1)
    fake_ai = BloatedThenLengthRepairAIService(repaired_text)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-length-retry-original-baseline",
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
            polished_text=previous_bloated_text,
            enhanced_text=previous_bloated_text,
            zhuque_reduced_text=previous_bloated_text,
            zhuque_reduce_attempt=1,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)
        original_length = count_text_length(original_text)
        reduced_length = count_text_length(segment.zhuque_reduced_text)

        assert session.status == "completed"
        assert fake_zhuque.detected_texts[0] == previous_bloated_text
        assert fake_zhuque.detected_texts[1] == repaired_text
        assert segment.zhuque_reduced_text == repaired_text
        assert reduced_length <= int(original_length * 1.1)
        assert reduced_length >= int(original_length * 0.9)
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
                "labels_ratio": {"0": 0.8, "1": 0.2, "2": 0.0},
                "segment_labels": [
                    {
                        "text": segment_texts[1],
                        "label": 0,
                        "conf": 0.99,
                        "order": 1,
                        "position": [
                            segment_starts[1],
                            segment_starts[1] + len(segment_texts[1]),
                        ],
                    },
                    {
                        "text": segment_texts[3],
                        "label": 0,
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
                "labels_ratio": {"0": 0.0, "1": 0.275, "2": 0.725},
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
                "labels_ratio": {"0": 0.0, "1": 0.275, "2": 0.725},
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
                        "label": 1,
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
        assert segment.zhuque_detect_count == 1
        assert segment.zhuque_reduce_attempt == 1
        assert segment.polished_text is None
        assert segment.enhanced_text is None
        assert segment.zhuque_reduced_text is None
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
        assert "朱雀逃逸改写" in fake_ai.polish_calls[2]["prompt"]
        assert "朱雀逃逸改写" in fake_ai.enhance_calls[2]["prompt"]
        assert "原文事实锚点" in fake_ai.polish_calls[2]["prompt"]
        assert "Nature / Science" not in fake_ai.polish_calls[2]["prompt"]
        assert "风格拟态专家" not in fake_ai.enhance_calls[2]["prompt"]

        trace = json.loads(session.zhuque_agent_trace)
        reduce_events = [event for event in trace["events"] if event["type"] == "reduce"]
        assert reduce_events[0]["rewrite_mode"] == "standard"
        assert reduce_events[1]["rewrite_mode"] == "standard"
        assert reduce_events[2]["rewrite_mode"] == "breakthrough"
    finally:
        db.close()


def test_ai_detect_reduce_activates_breakthrough_on_first_strong_stagnation(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 10])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 2, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-breakthrough-no-lag",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps({
                "version": 1,
                "threshold": 20.0,
                "events": [
                    {
                        "type": "reflection",
                        "round": 2,
                        "stagnation_count": 1,
                        "stubborn_segment_indices": [0],
                    }
                ],
            }, ensure_ascii=False),
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text="深度学习模型在医学影像分割任务中保持Dice系数稳定。" * 30,
            zhuque_reduced_text="深度学习模型在医学影像分割任务中保持Dice系数稳定。" * 30,
            zhuque_reduce_attempt=2,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)

        assert session.status == "completed"
        assert len(fake_ai.polish_calls) == 1
        assert "策略：强结构重写" in fake_ai.polish_calls[0]["prompt"]
        assert "朱雀逃逸改写" in fake_ai.polish_calls[0]["prompt"]
        assert "Nature / Science" not in fake_ai.polish_calls[0]["prompt"]

        trace = json.loads(session.zhuque_agent_trace)
        reduce_events = [event for event in trace["events"] if event["type"] == "reduce"]
        assert reduce_events[-1]["rewrite_mode"] == "breakthrough"
    finally:
        db.close()


def test_ai_detect_reduce_uses_paper_reconstruction_for_repeated_paper_stagnation(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 10])
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
            session_id="zhuque-paper-reconstruction",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps({
                "version": 1,
                "threshold": 20.0,
                "events": [
                    {
                        "type": "reflection",
                        "round": 5,
                        "stagnation_count": 2,
                        "stubborn_segment_indices": [0],
                    }
                ],
            }, ensure_ascii=False),
        )
        db.add(session)
        db.flush()
        segment = OptimizationSegment(
            session_id=session.id,
            segment_index=0,
            stage="ai_detect_reduce",
            original_text=(
                "本文围绕深度学习模型在医学影像分割任务中的应用展开研究。"
                "通过构建多尺度特征融合机制，模型能够有效提升边界区域识别能力，"
                "进一步为临床辅助诊断提供重要支撑。"
            ) * 8,
            zhuque_reduced_text=(
                "本文围绕深度学习模型在医学影像分割任务中的应用展开研究。"
                "通过构建多尺度特征融合机制，模型能够有效提升边界区域识别能力，"
                "进一步为临床辅助诊断提供重要支撑。"
            ) * 8,
            zhuque_reduce_attempt=5,
            status="pending",
        )
        db.add(segment)
        db.commit()

        service = OptimizationService(db, session)
        asyncio.run(service.start_optimization())

        db.refresh(session)

        assert session.status == "completed"
        assert len(fake_ai.polish_calls) == 1
        assert "rewrite_mode: paper_reconstruction" in fake_ai.polish_calls[0]["prompt"]
        assert "论文事实卡片" in fake_ai.polish_calls[0]["prompt"]
        assert "中文论文 AI 痕迹规则" in fake_ai.polish_calls[0]["prompt"]
        assert "候选 A" in fake_ai.polish_calls[0]["prompt"]
        assert "本地 AI 痕迹自检" in fake_ai.enhance_calls[0]["prompt"]
        assert "字数控制在原段落 90%-110%" in fake_ai.enhance_calls[0]["prompt"]

        trace = json.loads(session.zhuque_agent_trace)
        paper_events = [event for event in trace["events"] if event.get("rewrite_mode") == "paper_reconstruction"]
        assert paper_events
        paper_event = paper_events[0]
        assert paper_event["paper_language"] == "zh"
        assert "template_transition" in paper_event["paper_ai_patterns"]
        assert paper_event["candidate_count"] == 3
        assert paper_event["candidate_selector"] == "local_ai_pattern_score"
        assert paper_event["fact_card_count"] >= 1
    finally:
        db.close()


def test_ai_detect_reduce_rolls_back_round_when_recheck_rate_regresses(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 35, 100, 35])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 2, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-regression-rollback",
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
        with pytest.raises(RuntimeError, match="仍高于阈值"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        first_good_text = fake_zhuque.detected_texts[1]
        assert segment.zhuque_reduced_text == first_good_text
        assert len(fake_zhuque.detected_texts) == 3
        assert fake_zhuque.detected_texts[-1] != first_good_text
        assert segment.zhuque_detect_rate == 35

        trace = json.loads(session.zhuque_agent_trace)
        rollback_events = [event for event in trace["events"] if event.get("rollback_applied")]
        assert rollback_events
        assert rollback_events[0]["rolled_back_from_rate"] == 100
        assert rollback_events[0]["rolled_back_to_rate"] == 35
        assert "回滚保护" in rollback_events[0]["message"]
    finally:
        db.close()


def test_ai_detect_reduce_rejects_equal_rate_rewrite_without_extra_recheck(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([100, 45.1, 45.1])
    fake_ai = FakeAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 2, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-equal-rate-rollback",
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
        with pytest.raises(RuntimeError, match="仍高于阈值"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        db.refresh(segment)

        first_good_text = fake_zhuque.detected_texts[1]
        assert segment.zhuque_reduced_text == first_good_text
        assert len(fake_zhuque.detected_texts) == 3
        assert segment.zhuque_detect_rate == 45.1

        trace = json.loads(session.zhuque_agent_trace)
        rollback_events = [event for event in trace["events"] if event.get("rollback_applied")]
        assert rollback_events
        assert rollback_events[0]["rollback_reason"] == "not_improved"
        assert rollback_events[0]["rolled_back_from_rate"] == 45.1
        assert rollback_events[0]["rolled_back_to_rate"] == 45.1
    finally:
        db.close()


def test_ai_detect_reduce_rollback_restores_full_text_detect_metadata_for_all_segments(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_ai = FakeAIService()
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 2, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    segment_texts = ["短段甲" * 60, "短段乙" * 60]
    segment_starts = _joined_segment_starts(segment_texts)
    fake_zhuque = FakeZhuqueService(
        [
            {
                "success": True,
                "rate": 80,
                "labels_ratio": {"0": 0.8, "1": 0.2, "2": 0.0},
                "segment_labels": [
                    {
                        "text": segment_texts[1],
                        "label": 0,
                        "position": [segment_starts[1], segment_starts[1] + len(segment_texts[1])],
                    }
                ],
            },
            {
                "success": True,
                "rate": 45,
                "labels_ratio": {"0": 0.45, "1": 0.55, "2": 0.0},
                "segment_labels": [
                    {
                        "text": segment_texts[1],
                        "label": 0,
                        "position": [segment_starts[1], segment_starts[1] + len(segment_texts[1])],
                    }
                ],
            },
            {
                "success": True,
                "rate": 45,
                "labels_ratio": {"0": 0.45, "1": 0.55, "2": 0.0},
                "segment_labels": [
                    {
                        "text": segment_texts[1],
                        "label": 0,
                        "position": [segment_starts[1], segment_starts[1] + len(segment_texts[1])],
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-rollback-full-metadata",
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
        with pytest.raises(RuntimeError, match="仍高于阈值"):
            asyncio.run(service.start_optimization())

        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )

        assert [seg.zhuque_detect_rate for seg in segments] == [45, 45]
        assert [seg.zhuque_detect_count for seg in segments] == [2, 2]
        assert [json.loads(seg.zhuque_detect_result)["rate"] for seg in segments] == [45, 45]
        assert segments[0].zhuque_reduced_text is None
        assert segments[1].zhuque_reduced_text == fake_zhuque.detected_texts[1].split("\n\n")[1]

        trace = json.loads(session.zhuque_agent_trace)
        rollback_events = [event for event in trace["events"] if event.get("rollback_applied")]
        assert rollback_events[0]["restored_segment_indices"] == [1]
    finally:
        db.close()


def test_ai_detect_reduce_plateau_recovery_accepts_best_auto_candidate(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([25, 25, 24, 18])
    fake_ai = PlateauRecoveryAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-plateau-recovery-success",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps(
                {
                    "version": 1,
                    "threshold": 20,
                    "events": [
                        {
                            "type": "reflection",
                            "round": 9,
                            "stagnation_count": 2,
                            "stubborn_segment_indices": [0, 1],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(session)
        db.flush()
        for index in range(2):
            text = "自动探索B上一版低风险文本"
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    polished_text=f"上一版润色:{index}",
                    enhanced_text=f"上一版增强:{index}",
                    zhuque_reduced_text=f"上一版低风险文本:{index}",
                    zhuque_reduce_attempt=10,
                    zhuque_detect_rate=25,
                    zhuque_detect_count=10,
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
        assert len(fake_zhuque.detected_texts) == 4
        assert [seg.zhuque_reduced_text for seg in segments] == [
            "自动探索B:上一版低风险文本:0",
            "自动探索B:上一版低风险文本:1",
        ]
        assert any("卡点候选A" in call["prompt"] for call in fake_ai.polish_calls)
        assert any("卡点候选B" in call["prompt"] for call in fake_ai.polish_calls)

        trace = json.loads(session.zhuque_agent_trace)
        recovery_events = [event for event in trace["events"] if event.get("type") == "plateau_recovery"]
        assert recovery_events
        assert recovery_events[0]["status"] == "accepted"
        assert recovery_events[0]["candidate_count"] == 2
        assert recovery_events[0]["selected_candidate_id"] == "B"
        assert trace["final"]["status"] == "completed"
    finally:
        db.close()


def test_ai_detect_reduce_plateau_recovery_sweeps_stubborn_segments_after_bulk_candidates_fail(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=200, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([25, 25, 25, 25, 25, 18])
    fake_ai = PlateauRecoveryAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-plateau-recovery-segment-sweep",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps(
                {
                    "version": 1,
                    "threshold": 20,
                    "events": [
                        {
                            "type": "reflection",
                            "round": 9,
                            "stagnation_count": 2,
                            "stubborn_segment_indices": [0, 1],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(session)
        db.flush()
        for index in range(2):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text="局部探索上一版低风险文本",
                    polished_text=f"上一版润色:{index}",
                    enhanced_text=f"上一版增强:{index}",
                    zhuque_reduced_text=f"上一版低风险文本:{index}",
                    zhuque_reduce_attempt=10,
                    zhuque_detect_rate=25,
                    zhuque_detect_count=10,
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
        assert len(fake_zhuque.detected_texts) == 6
        assert [seg.zhuque_reduced_text for seg in segments] == [
            "局部探索S1:上一版低风险文本:0",
            "上一版低风险文本:1",
        ]
        assert any("卡点候选C" in call["prompt"] for call in fake_ai.polish_calls)
        assert any("逐段候选S1" in call["prompt"] for call in fake_ai.polish_calls)

        trace = json.loads(session.zhuque_agent_trace)
        recovery_events = [event for event in trace["events"] if event.get("type") == "plateau_recovery"]
        assert recovery_events
        assert recovery_events[-1]["status"] == "accepted"
        assert recovery_events[-1]["candidate_count"] == 4
        assert recovery_events[-1]["selected_candidate_id"] == "S1:0"
        assert recovery_events[-1]["selected_candidate_phase"] == "segment_sweep"
        assert trace["final"]["status"] == "completed"
    finally:
        db.close()


def test_ai_detect_reduce_exits_plateau_only_after_auto_candidates_fail(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=200, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30])
    fake_ai = PlateauRecoveryAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-plateau-recovery-failed",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps(
                {
                    "version": 1,
                    "threshold": 20,
                    "events": [
                        {
                            "type": "reflection",
                            "round": 9,
                            "stagnation_count": 2,
                            "stubborn_segment_indices": [0, 1],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(session)
        db.flush()
        for index in range(2):
            text = "自动探索B上一版低风险文本"
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    polished_text=f"上一版润色:{index}",
                    enhanced_text=f"上一版增强:{index}",
                    zhuque_reduced_text=f"上一版低风险文本:{index}",
                    zhuque_reduce_attempt=10,
                    zhuque_detect_rate=30,
                    zhuque_detect_count=10,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match="自动探索候选仍未突破"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )

        assert session.status == "failed"
        assert len(fake_zhuque.detected_texts) == 12
        assert [seg.zhuque_reduced_text for seg in segments] == [
            "上一版低风险文本:0",
            "上一版低风险文本:1",
        ]

        trace = json.loads(session.zhuque_agent_trace)
        recovery_events = [event for event in trace["events"] if event.get("type") == "plateau_recovery"]
        assert recovery_events
        assert recovery_events[-1]["status"] == "failed"
        assert recovery_events[-1]["candidate_count"] == 10
        assert any(
            item.get("phase") == "segment_sweep"
            for item in recovery_events[-1]["candidate_rates"]
        )
        deep_events = [event for event in trace["events"] if event.get("type") == "plateau_deep_reconstruction"]
        assert deep_events
        assert deep_events[-1]["status"] == "failed"
        plateau_events = [event for event in trace["events"] if event.get("type") == "plateau_exit"]
        assert plateau_events
        assert plateau_events[0]["action"] == "auto_recovery_exhausted"
    finally:
        db.close()


def test_ai_detect_reduce_deep_reconstruction_runs_after_plateau_candidates_fail(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=300, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([25, 25, 25, 25, 25, 25, 25, 25, 25, 18])
    fake_ai = DeepReconstructionAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-deep-reconstruction-success",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps(
                {
                    "version": 1,
                    "threshold": 20,
                    "events": [
                        {
                            "type": "reflection",
                            "round": 9,
                            "stagnation_count": 2,
                            "stubborn_segment_indices": [0, 1],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(session)
        db.flush()
        for index in range(2):
            text = f"上一版低风险文本{index}" * 14
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text=text,
                    polished_text=f"上一版润色:{index}",
                    enhanced_text=f"上一版增强:{index}",
                    zhuque_reduced_text=text,
                    zhuque_reduce_attempt=10,
                    zhuque_detect_rate=25,
                    zhuque_detect_count=10,
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
        assert len(fake_zhuque.detected_texts) == 10
        assert [seg.zhuque_reduced_text for seg in segments] == [
            f"深度重构证据优先:{'上一版低风险文本0' * 14}",
            f"深度重构证据优先:{'上一版低风险文本1' * 14}",
        ]
        assert any("深度重构路线:evidence_first" in call["prompt"] for call in fake_ai.polish_calls)

        trace = json.loads(session.zhuque_agent_trace)
        deep_events = [event for event in trace["events"] if event.get("type") == "plateau_deep_reconstruction"]
        assert deep_events
        assert deep_events[-1]["status"] == "accepted"
        assert deep_events[-1]["selected_route"] == "evidence_first"
        assert deep_events[-1]["candidate_count"] == 1
        assert deep_events[-1]["fact_card_count"] >= 1
        assert trace["final"]["status"] == "completed"
    finally:
        db.close()


def test_ai_detect_reduce_marks_detector_floor_when_all_safe_candidates_flatline(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=300, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([24.52] * 12)
    fake_ai = DeepReconstructionAIService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: _install_fake_ai_services(self, fake_ai))
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_THRESHOLD", 20.0, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_MAX_REDUCE_ROUNDS", 5, raising=False)
    monkeypatch.setattr(optimization_service_module.settings, "ZHUQUE_DETECT_INTERVAL", 0, raising=False)

    db = SessionLocal()
    try:
        session = OptimizationSession(
            user_id=user_id,
            session_id="zhuque-detector-floor",
            original_text="原始文本",
            current_stage="ai_detect_reduce",
            status="queued",
            processing_mode="ai_detect_reduce",
            billing_mode="platform",
            charge_status="not_charged",
            zhuque_agent_trace=json.dumps(
                {
                    "version": 1,
                    "threshold": 20,
                    "events": [
                        {
                            "type": "reflection",
                            "round": 9,
                            "stagnation_count": 2,
                            "stubborn_segment_indices": [0, 1],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(session)
        db.flush()
        for index in range(2):
            db.add(
                OptimizationSegment(
                    session_id=session.id,
                    segment_index=index,
                    stage="ai_detect_reduce",
                    original_text="深度学习模型在医学影像分割任务中保持Dice系数稳定。" * 12,
                    polished_text=f"上一版润色:{index}",
                    enhanced_text=f"上一版增强:{index}",
                    zhuque_reduced_text=f"上一版低风险文本:{index}",
                    zhuque_reduce_attempt=10,
                    zhuque_detect_rate=24.52,
                    zhuque_detect_count=10,
                    status="pending",
                )
            )
        db.commit()

        service = OptimizationService(db, session)
        with pytest.raises(RuntimeError, match="检测地板"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id == session.id)
            .order_by(OptimizationSegment.segment_index)
            .all()
        )

        assert session.status == "failed"
        assert [seg.zhuque_reduced_text for seg in segments] == [
            "上一版低风险文本:0",
            "上一版低风险文本:1",
        ]

        trace = json.loads(session.zhuque_agent_trace)
        floor_events = [event for event in trace["events"] if event.get("type") == "detector_floor"]
        assert floor_events
        assert floor_events[-1]["rate"] == 24.52
        assert floor_events[-1]["recommended_threshold"] == 26.0
        assert floor_events[-1]["rate_spread"] == 0.0
        assert "检测地板" in trace["final"]["diagnosis"]
    finally:
        db.close()


def test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=100, zhuque_free_uses_remaining=20)
    fake_zhuque = FakeZhuqueService([
        {"rate": 80, "labels_ratio": {"0": 0.2, "1": 0.0, "2": 0.8}},
        {"rate": 79.8, "labels_ratio": {"0": 0.0, "1": 0.202, "2": 0.798}},
        {"rate": 79.6, "labels_ratio": {"0": 0.0, "1": 0.204, "2": 0.796}},
        {"rate": 10, "labels_ratio": {"0": 0.0, "1": 0.9, "2": 0.1}},
    ])
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
            session_id="zhuque-convergence-reflection",
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
        assert "策略：轻度自然化" in fake_ai.polish_calls[0]["prompt"]
        assert "策略：句式重组" in fake_ai.polish_calls[1]["prompt"]
        assert "策略：强结构重写" in fake_ai.polish_calls[2]["prompt"]
        assert "顽固段落强改写策略" in fake_ai.polish_calls[2]["prompt"]

        trace = json.loads(session.zhuque_agent_trace)
        reduce_events = [event for event in trace["events"] if event["type"] == "reduce"]
        reflection_events = [event for event in trace["events"] if event["type"] == "reflection"]
        evolution_events = [event for event in trace["events"] if event["type"] == "prompt_evolution"]

        assert reduce_events[0]["decision"] == "minor_drop_upgrade_strategy"
        assert reduce_events[1]["decision"] == "minor_drop_upgrade_strategy"
        assert len(reflection_events) >= 2
        assert reflection_events[0]["stagnation_count"] == 1
        assert reflection_events[0]["stubborn_segment_indices"] == [0]
        assert reflection_events[0]["next_strategy"] == "句式重组"
        assert reflection_events[1]["stagnation_count"] == 2
        assert reflection_events[1]["action"] == "force_stronger_strategy"
        assert reflection_events[1]["next_strategy"] == "强结构重写"
        assert "连续" in reflection_events[1]["message"]
        assert evolution_events
        assert evolution_events[0]["source"] in {"fallback", "memory"}
        assert evolution_events[0]["safety_status"] == "safe"
        assert evolution_events[0]["failure_signature"]["dominant_label"] == "suspicious"
        assert "顽固段落强改写策略" in evolution_events[0]["prompt_patch"]
        memory = db.query(ZhuquePromptMemory).filter(ZhuquePromptMemory.id == evolution_events[0]["memory_id"]).one()
        assert memory.uses >= 1
    finally:
        db.close()


def test_ai_detect_reduce_preflights_zhuque_before_segment_loop(monkeypatch):
    import app.services.optimization_service as optimization_service_module

    user_id = _create_user(credit_balance=20, zhuque_free_uses_remaining=20)
    fake_zhuque = UnavailableZhuqueService()
    monkeypatch.setattr(optimization_service_module, "zhuque_service", fake_zhuque)

    init_calls = []
    monkeypatch.setattr(OptimizationService, "_init_ai_services", lambda self: init_calls.append(self.session_obj.session_id))
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
        with pytest.raises(RuntimeError, match="微信扫码凭证不可用"):
            asyncio.run(service.start_optimization())

        db.refresh(session)
        assert fake_zhuque.start_calls == 1
        assert fake_zhuque.detect_calls == 0
        assert init_calls == []
        assert session.status == "failed"
        assert "微信扫码凭证不可用" in session.error_message
        assert "微信扫码登录朱雀" in session.error_message
        assert "无头 API" in session.error_message
    finally:
        db.close()
