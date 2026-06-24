"""
朱雀 AI 检测 API — 微信扫码凭证 + 无头 WebSocket 版。

登录链路：zhuque_pkg/capture_zhuque_creds.py 打开一次可见浏览器，微信扫码后
保存 creds_latest.json。检测链路：后端直接连接朱雀 WebSocket API，不再依赖
旧版本地页面控制 / matrix 页面 DOM。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import websockets


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 检测结果标签（GankAIGC 内部契约）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 0 = AI 特征，1 = 人工特征，2 = 疑似/混合
LABEL_NAMES = {
    0: "AI生成",
    1: "人工编写",
    2: "混合/可疑",
}

LABEL_EMOJI = {
    0: "🤖",
    1: "✍️",
    2: "⚠️",
}

ZHUQUE_HTTP_BASE_URL = "https://matrix.tencent.com"
ZHUQUE_WS_URL = "wss://matrix.tencent.com/ai_gen_txt_server/getClassify"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _coerce_ratio_value(value) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    # 朱雀不同结果路径可能返回 0-1 或 0-100，这里统一成 0-1。
    if ratio > 1.0:
        ratio = ratio / 100.0
    return max(0.0, min(ratio, 1.0))


def _coerce_rate_value(value) -> Optional[float]:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 1.0:
        rate *= 100.0
    return max(0.0, min(rate, 100.0))


def _failure_zhuque_result(
    message: str,
    text_length: int,
    *,
    remaining_uses: int = -1,
    source: str = "headless_api",
) -> dict:
    return {
        "success": False,
        "message": message,
        "rate": None,
        "risk_rate": None,
        "rate_label": "",
        "labels_ratio": {},
        "alert_text": "",
        "alert_title": "",
        "remaining_uses": remaining_uses,
        "text_length": text_length,
        "source": source,
    }


def _zhuque_failure_message(data: dict) -> Optional[str]:
    message = str(data.get("msg") or data.get("message") or data.get("error") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    if data.get("success") is False:
        return message or "朱雀检测返回失败"
    if status in {"failed", "fail", "error"}:
        return message or "朱雀检测返回失败"
    if "invalid request" in message.lower() or "invalid_request" in message.lower():
        return message or "Invalid request"
    return None


def _parse_remaining_uses(text: str) -> int:
    import re

    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else -1


def _normalise_login_text(text: str) -> str:
    import re

    return re.sub(r"\s+", "", str(text or "").strip()).lower()


def _is_login_prompt_text(text: str) -> bool:
    """Detect Zhuque's logged-out account placeholder.

    The real page can render the top-right login entry as `.user-name = Login`.
    If that placeholder is persisted into `creds_latest.json`, the old code kept
    showing the anonymous button quota (for example 16 left) as if an account
    was still logged in.
    """
    return _normalise_login_text(text) in {
        "login",
        "log in",
        "signin",
        "sign in",
        "登录",
        "微信登录",
        "扫码登录",
    }


def _coerce_remaining_uses(*values) -> int:
    """Normalize Zhuque quota values from API numbers or UI text.

    Live Zhuque can expose the remaining quota as:
    - `availableUses: 18`
    - `remaining_uses: "18"`
    - button text like `Detect now(18 left)`
    - Chinese quota text like `今日剩余 18 次`
    """
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            remaining = int(value)
            if remaining >= 0:
                return remaining
            continue
        remaining = _parse_remaining_uses(str(value))
        if remaining >= 0:
            return remaining
    return -1


def _unwrap_token_value(value) -> str:
    """Zhuque localStorage may store aiGenAccessToken as JSON {value, expiry, uid}."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("value") or value.get("token") or value.get("access_token") or "")
    text = str(value)
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text
    if isinstance(parsed, dict):
        return str(parsed.get("value") or parsed.get("token") or parsed.get("access_token") or text)
    return text


def _default_credentials_file() -> Path:
    env_path = os.environ.get("ZHUQUE_CREDENTIALS_FILE")
    if env_path:
        return Path(env_path).expanduser()

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "zhuque_pkg" / "creds_latest.json",  # repo root when running from package/backend/app/services
        here.parents[3] / "zhuque_pkg" / "creds_latest.json",  # package/zhuque_pkg for bundled layouts
        Path.cwd() / "zhuque_pkg" / "creds_latest.json",
        Path.cwd().parent / "zhuque_pkg" / "creds_latest.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _extract_credentials(raw: dict) -> dict:
    local_storage = raw.get("localStorage") or raw.get("local_storage") or {}
    raw_cookies = raw.get("cookies") or raw.get("cookieString") or raw.get("cookie_string") or ""
    cookie_token = ""
    if isinstance(raw_cookies, list):
        for item in raw_cookies:
            if (
                isinstance(item, dict)
                and str(item.get("name", "")).lower() in {"access_token", "accesstoken"}
                and item.get("value")
            ):
                cookie_token = str(item["value"])
                break
        cookies = "; ".join(
            f"{item.get('name')}={item.get('value')}"
            for item in raw_cookies
            if isinstance(item, dict) and item.get("name") is not None
        )
    else:
        cookies = raw_cookies or ""

    raw_token = _unwrap_token_value(raw.get("access_token"))
    storage_token = _unwrap_token_value(local_storage.get("aiGenAccessToken"))
    if not storage_token:
        for key, value in local_storage.items():
            lower_key = str(key).lower()
            if value and "token" in lower_key and ("access" in lower_key or "auth" in lower_key):
                storage_token = _unwrap_token_value(value)
                break

    access_token = raw_token or storage_token or cookie_token or ""
    fp = raw.get("fp") or local_storage.get("fp") or ""
    user_name = raw.get("user_name") or raw.get("userName") or ""
    if _is_login_prompt_text(user_name):
        user_name = ""
    logged_out_placeholder = not access_token and not user_name
    remaining_uses = _coerce_remaining_uses(
        raw.get("remaining_uses"),
        raw.get("remainingUses"),
        raw.get("availableUses"),
        raw.get("quota_text"),
        raw.get("quotaText"),
    )
    if logged_out_placeholder:
        fp = ""
        cookies = ""
        remaining_uses = -1

    return {
        "access_token": access_token,
        "fp": fp,
        "cookies": cookies or "",
        "user_name": user_name,
        "quota_text": raw.get("quota_text") or raw.get("quotaText") or "",
        "remaining_uses": remaining_uses,
        "captured_at": raw.get("captured_at") or raw.get("timestamp") or "",
        "raw": raw,
    }


def _generate_fp() -> str:
    # 仅作为匿名/首次握手兜底；微信扫码凭证可提供真实 fp。
    return uuid.uuid4().hex


def parse_zhuque_websocket_result(payload: str, text_length: int) -> Optional[dict]:
    """Parse a terminal Zhuque WebSocket result frame into the public result shape.

    GankAIGC 内部契约固定为：0=AI，1=人工，2=疑似/混合。
    朱雀网页历史结果里有过 0/1 语义切换，因此这里会用 confidence/rate 做一次
    归一化，避免把人工占比错当 AI 风险。
    """
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None

    if data.get("status") != "success":
        return None

    return normalize_zhuque_result(data, text_length=text_length, source="websocket")


def _infer_and_convert_labels(raw_labels: dict, ai_rate: Optional[float]) -> tuple[dict, dict[int, int]]:
    """Return project labels_ratio plus raw-label -> project-label mapping.

    Current live Zhuque web UI renders text chart as 0=human, 1=AI, 2=suspicious;
    earlier package docs described 0=AI. We infer from confidence/rate when present,
    and expose only the stable GankAIGC contract: 0=AI, 1=human, 2=suspicious.
    """
    if not isinstance(raw_labels, dict) or not raw_labels:
        return {}, {0: 0, 1: 1, 2: 2}

    raw = {str(key): _coerce_ratio_value(value) for key, value in (raw_labels or {}).items()}
    raw0 = raw.get("0", 0.0)
    raw1 = raw.get("1", 0.0)
    raw2 = raw.get("2", 0.0)

    ai_ratio_from_rate = None
    if ai_rate is not None:
        ai_ratio_from_rate = _coerce_ratio_value(ai_rate)

    if ai_ratio_from_rate is not None:
        raw1_distance = abs(raw1 - ai_ratio_from_rate)
        raw0_distance = abs(raw0 - ai_ratio_from_rate)
        raw_one_is_ai = raw1_distance < raw0_distance
    else:
        # 缺少 confidence 时按新包契约兜底，避免破坏既有 GankAIGC 测试。
        raw_one_is_ai = False

    if raw_one_is_ai:
        labels_ratio = {"0": raw1, "1": raw0, "2": raw2}
        label_map = {0: 1, 1: 0, 2: 2}
    else:
        labels_ratio = {"0": raw0, "1": raw1, "2": raw2}
        label_map = {0: 0, 1: 1, 2: 2}
    return labels_ratio, label_map


def _convert_segment_labels(segment_labels: Any, label_map: dict[int, int]) -> list:
    converted = []
    if not isinstance(segment_labels, list):
        return converted
    for item in segment_labels:
        if not isinstance(item, dict):
            converted.append(item)
            continue
        cloned = dict(item)
        try:
            raw_label = int(cloned.get("label"))
        except (TypeError, ValueError):
            converted.append(cloned)
            continue
        cloned["label"] = label_map.get(raw_label, raw_label)
        converted.append(cloned)
    return converted


def normalize_zhuque_result(data: dict, *, text_length: int, source: str) -> dict:
    failure_message = _zhuque_failure_message(data)
    if failure_message:
        return _failure_zhuque_result(
            failure_message,
            text_length,
            remaining_uses=_coerce_remaining_uses(
                data.get("availableUses"),
                data.get("remaining_uses"),
                data.get("remainingUses"),
                data.get("remaining"),
                data.get("quota_text"),
                data.get("quotaText"),
                data.get("button_text"),
            ),
            source=source,
        )

    raw_rate = _coerce_rate_value(
        data.get("confidence", data.get("rate", data.get("ai_generated")))
    )
    raw_labels = data.get("labels_ratio") or data.get("labelsRatio") or {}
    labels_ratio, label_map = _infer_and_convert_labels(raw_labels, raw_rate)
    if not labels_ratio and raw_rate is not None:
        ai_ratio_from_rate = _coerce_ratio_value(raw_rate)
        labels_ratio = {
            "0": ai_ratio_from_rate,
            "1": round(max(0.0, 1.0 - ai_ratio_from_rate), 6),
            "2": 0.0,
        }

    ai_ratio = labels_ratio.get("0", 0.0)
    suspicious_ratio = labels_ratio.get("2", 0.0)
    rate = round(raw_rate if raw_rate is not None else ai_ratio * 100, 2)
    if labels_ratio:
        risk_rate = round(max(ai_ratio, suspicious_ratio) * 100, 2)
    elif raw_rate is not None:
        risk_rate = rate
    else:
        return _failure_zhuque_result(
            data.get("msg") or data.get("message") or "朱雀检测响应缺少有效检测分数",
            text_length,
            remaining_uses=_coerce_remaining_uses(
                data.get("availableUses"),
                data.get("remaining_uses"),
                data.get("remainingUses"),
                data.get("remaining"),
                data.get("quota_text"),
                data.get("quotaText"),
                data.get("button_text"),
            ),
            source=source,
        )

    if ai_ratio >= 0.5:
        alert_text = "未发现明显的人工创作特征"
    elif suspicious_ratio >= 0.5:
        alert_text = "人工创作特征较弱或混合可疑"
    else:
        alert_text = "人工创作特征较明显"

    default_rate_label = "WebSocket检测结果" if source == "websocket" else "朱雀无头检测结果"

    remaining_uses = _coerce_remaining_uses(
        data.get("availableUses"),
        data.get("remaining_uses"),
        data.get("remainingUses"),
        data.get("remaining"),
        data.get("quota_text"),
        data.get("quotaText"),
        data.get("button_text"),
    )

    return {
        "success": True,
        "rate": rate,
        "risk_rate": risk_rate,
        "rate_label": data.get("rateLabel") or data.get("rate_label") or default_rate_label,
        "labels_ratio": labels_ratio,
        "alert_text": data.get("alert_text") or alert_text,
        "alert_title": data.get("alert_title", ""),
        "message": data.get("msg") or data.get("message") or "",
        "remaining_uses": remaining_uses,
        "text_length": text_length,
        "confidence": data.get("confidence"),
        "segment_labels": _convert_segment_labels(data.get("segment_labels", []), label_map),
        "content_type": data.get("content_type"),
        "feedback_token": data.get("feedback_token"),
        "source": source,
    }


class ZhuqueAPI:
    """微信扫码凭证 + 朱雀 WebSocket 无头检测客户端。"""

    def __init__(
        self,
        cdp_port: int | None = None,
        debug: bool = False,
        credentials_file: str | Path | None = None,
        ws_url: str = ZHUQUE_WS_URL,
        http_base_url: str = ZHUQUE_HTTP_BASE_URL,
    ):
        # cdp_port 保留在签名中兼容旧调用；新链路不再使用本地页面调试端口。
        self.cdp_port = cdp_port
        self.debug = debug
        self.credentials_file = Path(credentials_file).expanduser() if credentials_file else _default_credentials_file()
        self.ws_url = ws_url
        self.http_base_url = http_base_url.rstrip("/")
        self._credentials_cache: Optional[dict] = None

    def _playwright_browsers_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / ".playwright-browsers"

    # ── 凭证 ─────────────────────────────────────────────

    def load_credentials(self, *, refresh: bool = False) -> dict:
        if self._credentials_cache is not None and not refresh:
            return dict(self._credentials_cache)
        if not self.credentials_file.exists():
            raise RuntimeError(
                f"未找到朱雀微信登录凭证: {self.credentials_file}。"
                "请先点击“微信扫码登录朱雀”或运行 zhuque_pkg/capture_zhuque_creds.py"
            )
        try:
            raw = json.loads(self.credentials_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"朱雀凭证文件不是有效 JSON: {self.credentials_file}") from exc
        creds = _extract_credentials(raw)
        if not creds.get("access_token") and not creds.get("fp"):
            raise RuntimeError("朱雀凭证缺少 access_token/fp，请重新微信扫码登录")
        self._credentials_cache = creds
        return dict(creds)

    def forget_credentials_cache(self) -> None:
        """Forget in-memory credential cache after creds_latest.json is replaced/removed."""
        self._credentials_cache = None

    def _session_status_file(self) -> Path:
        return self.credentials_file.parent / "session_status.json"

    def _read_session_status(self) -> Optional[dict]:
        status_file = self._session_status_file()
        if not status_file.exists():
            return None
        try:
            status = json.loads(status_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(status, dict):
            return None
        return status

    def _status_from_session_file(self, status: dict) -> dict:
        connected = bool(status.get("connected") or status.get("ready"))
        remaining_uses = _coerce_remaining_uses(status.get("remaining_uses"), status.get("quota_text"))
        return {
            "ready": connected,
            "connected": connected,
            "page_found": connected,
            "has_token": bool(status.get("has_token")) if connected else False,
            "remaining_uses": remaining_uses,
            "button_enabled": connected or remaining_uses != 0,
            "credential_file": str(self.credentials_file),
            "auth_mode": "headless_api",
            "login_mode": "wechat_qr",
            "user_name": status.get("user_name") or "",
            "quota_text": status.get("quota_text") or "",
            "captured_at": status.get("updated_at") or "",
            "session_status_file": str(self._session_status_file()),
            "message": status.get("message") or ("朱雀网页已登录" if connected else "朱雀网页显示未登录"),
        }

    def credential_status(self) -> dict:
        session_status = self._read_session_status()
        if session_status and session_status.get("connected") is False:
            return self._status_from_session_file(session_status)

        try:
            creds = self.load_credentials(refresh=True)
        except RuntimeError as exc:
            has_stale_credentials_file = self.credentials_file.exists()
            if session_status is not None:
                return self._status_from_session_file(session_status)
            return {
                "ready": False,
                "connected": False,
                "page_found": False,
                "has_token": False,
                "remaining_uses": -1,
                "button_enabled": True,
                "credential_file": str(self.credentials_file),
                "auth_mode": "headless_api",
                "login_mode": "wechat_qr",
                "user_name": "",
                "quota_text": "",
                "captured_at": "",
                "message": "朱雀网页显示未登录，可使用免费次数或重新扫码登录" if has_stale_credentials_file else str(exc),
            }

        quota_text = creds.get("quota_text") or ""
        has_token = bool(creds.get("access_token"))
        remaining_uses = (
            _coerce_remaining_uses(creds.get("remaining_uses"), quota_text)
            if has_token
            else -1
        )
        return {
            "ready": has_token,
            "connected": has_token,
            "page_found": has_token,
            "has_token": has_token,
            "remaining_uses": remaining_uses,
            "button_enabled": has_token or remaining_uses != 0,
            "credential_file": str(self.credentials_file),
            "auth_mode": "headless_api",
            "login_mode": "wechat_qr",
            "user_name": creds.get("user_name") or "",
            "quota_text": quota_text,
            "captured_at": creds.get("captured_at") or "",
            "session_status_file": str(self._session_status_file()),
            "message": "朱雀微信凭证已就绪，检测将走无头 API" if has_token else "朱雀凭证缺少 token，可尝试未登录免费次数或重新扫码",
        }

    async def status(self) -> dict:
        """兼容旧 status()，返回无头 API 凭证状态。"""
        return self.credential_status()

    async def peek_remaining_uses(self, timeout: float = 3.0) -> Optional[int]:
        """Read live Zhuque quota from the initial WebSocket auth frames.

        This sends only the saved access token/fp and closes the connection before
        captcha/text submission, so it does not consume a detection use.
        """
        try:
            creds = self.load_credentials(refresh=True)
        except RuntimeError:
            return None

        auth_payload = {"access_token": creds.get("access_token")} if creds.get("access_token") else {"fp": creds.get("fp") or _generate_fp()}
        headers = self._ws_headers(creds)
        try:
            ws = await asyncio.wait_for(self._connect(headers), timeout=max(timeout, 0.1))
        except Exception:
            return None

        deadline = time.time() + max(timeout, 0.1)
        try:
            await ws.send(json.dumps(auth_payload, ensure_ascii=False))
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if data.get("status") == "limited":
                    return 0

                remaining_uses = _coerce_remaining_uses(
                    data.get("availableUses"),
                    data.get("remaining_uses"),
                    data.get("remainingUses"),
                    data.get("remaining"),
                    data.get("quota_text"),
                    data.get("quotaText"),
                    data.get("button_text"),
                    data.get("msg"),
                )
                if remaining_uses >= 0:
                    return remaining_uses

                if data.get("access_token"):
                    await ws.send(json.dumps({"access_token": data["access_token"]}, ensure_ascii=False))
        except Exception:
            return None
        finally:
            try:
                await asyncio.wait_for(ws.close(), timeout=0.5)
            except Exception:
                pass
        return None

    # ── WebSocket 检测 ───────────────────────────────────

    def _ws_headers(self, creds: dict) -> list[tuple[str, str]]:
        headers = [
            ("User-Agent", DEFAULT_USER_AGENT),
            ("Pragma", "no-cache"),
            ("Cache-Control", "no-cache"),
        ]
        if creds.get("cookies"):
            headers.append(("Cookie", creds["cookies"]))
        return headers

    async def _connect(self, headers: list[tuple[str, str]]):
        # websockets 12 uses extra_headers; newer releases renamed it to
        # additional_headers. Try both without leaking either kwarg to the event loop.
        common_kwargs = {
            "origin": self.http_base_url,
            "max_size": 2**24,
            "open_timeout": 3.0,
            "close_timeout": 0.2,
            "ping_interval": None,
        }
        for header_kwarg in ("extra_headers", "additional_headers"):
            try:
                return await websockets.connect(
                    self.ws_url,
                    **{header_kwarg: headers},
                    **common_kwargs,
                )
            except TypeError as exc:
                if header_kwarg not in str(exc):
                    raise
        return await websockets.connect(
            self.ws_url,
            **common_kwargs,
        )

    async def _poll_cos_result(self, cos: str, start_time: int, text_length: int, creds: dict, timeout: float) -> dict:
        deadline = time.time() + timeout
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        if creds.get("cookies"):
            headers["Cookie"] = creds["cookies"]
        async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
            while time.time() < deadline:
                response = await client.get(
                    f"{self.http_base_url}/user/detect/result",
                    params={"cos": cos, "startTime": start_time},
                )
                payload = response.json()
                if payload.get("success") is True and payload.get("data"):
                    result_data = payload["data"]
                    if isinstance(result_data, str):
                        result_data = json.loads(result_data)
                    return normalize_zhuque_result(result_data, text_length=text_length, source="websocket_poll")
                if payload.get("success") is False:
                    return self._failure(payload.get("message") or "朱雀检测结果轮询失败", text_length)
                await asyncio.sleep(5)
        return self._failure(f"检测结果轮询超时 ({timeout}s)", text_length)

    async def _detect_with_page(self, text: str, timeout: float, *, reason: str = "") -> dict:
        """Fallback to the real Zhuque page so TencentCaptcha generates a valid ticket."""
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return self._failure(
                f"朱雀无头 API 验证失败，且当前环境未安装 Playwright，无法启用真实页面兜底。{reason}",
                len(text),
            )

        state_file = self.credentials_file.parent / "browser_state.json"

        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self._playwright_browsers_path()))
        pw = await async_playwright().start()
        browser = None
        try:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx_kwargs = {
                "viewport": {"width": 1280, "height": 720},
                "user_agent": DEFAULT_USER_AGENT,
            }
            if state_file.exists():
                ctx_kwargs["storage_state"] = str(state_file)
            ctx = await browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()
            await page.goto(f"{self.http_base_url}/ai-detect/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            await page.evaluate(
                """() => {
                    const button = document.querySelector('.clear-btn')
                        || [...document.querySelectorAll('button')].find(b => /清空|Clear/i.test(b.textContent || ''));
                    if (button) button.click();
                }"""
            )
            await page.wait_for_timeout(500)
            set_result = await page.evaluate(
                """(text) => {
                    const ta = document.querySelector('.el-textarea__inner');
                    if (!ta) return 'NO_TEXTAREA';
                    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(ta, text);
                    ta.dispatchEvent(new Event('input', {bubbles: true}));
                    return 'SET:' + ta.value.length;
                }""",
                text,
            )
            if "NO_TEXTAREA" in str(set_result):
                return self._failure("朱雀真实页面兜底失败：找不到文本输入框", len(text))

            await page.wait_for_timeout(500)
            click_result = await page.evaluate(
                """() => {
                    const button = document.querySelector('.submit-btn')
                        || [...document.querySelectorAll('button')].find(b => /立即检测|Detect/i.test(b.textContent || ''));
                    if (!button) return 'NOT_FOUND';
                    if (button.disabled) return 'DISABLED:' + button.textContent;
                    button.click();
                    return 'CLICKED:' + button.textContent;
                }"""
            )
            if "NOT_FOUND" in str(click_result):
                return self._failure("朱雀真实页面兜底失败：找不到检测按钮", len(text))
            if "DISABLED" in str(click_result):
                return self._failure("朱雀真实页面兜底失败：检测按钮被禁用，可能文本长度不足或次数用尽", len(text))

            deadline = time.time() + timeout
            while time.time() < deadline:
                await page.wait_for_timeout(1000)
                data = await page.evaluate(
                    """() => {
                        const el = document.querySelector('.ai-detection-result');
                        const alert = document.querySelector('.el-alert__description');
                        const title = document.querySelector('.el-alert__title');
                        const btn = document.querySelector('.submit-btn');
                        let vue = null;
                        if (el && el.__vue__) {
                            vue = {
                                type: el.__vue__.type,
                                processing: el.__vue__.processing,
                                rate: el.__vue__.rate,
                                rateLabel: el.__vue__.rateLabel,
                                labelsRatio: el.__vue__.labelsRatio,
                                msg: el.__vue__.msg || ''
                            };
                        }
                        return {
                            vue,
                            alert: alert ? alert.textContent.trim() : '',
                            alert_title: title ? title.textContent.trim() : '',
                            button_text: btn ? btn.textContent.trim() : ''
                        };
                    }"""
                )
                vue = data.get("vue") or {}
                if vue.get("type") and not vue.get("processing") and vue.get("rate") is not None:
                    payload = {
                        "confidence": vue.get("rate"),
                        "rateLabel": vue.get("rateLabel"),
                        "labelsRatio": vue.get("labelsRatio") or {},
                        "msg": vue.get("msg") or "",
                        "alert_text": (data.get("alert") or "").replace("Report", "").replace("下载报告", "").strip(),
                        "alert_title": data.get("alert_title") or "",
                        "availableUses": _parse_remaining_uses(data.get("button_text") or ""),
                    }
                    return normalize_zhuque_result(payload, text_length=len(text), source="page_fallback")

            return self._failure(f"朱雀真实页面兜底检测超时 ({timeout}s)", len(text))
        except Exception as exc:
            return self._failure(f"朱雀真实页面兜底失败: {exc}", len(text))
        finally:
            if browser is not None:
                await browser.close()
            await pw.stop()

    def _failure(self, message: str, text_length: int, *, remaining_uses: int = -1) -> dict:
        return _failure_zhuque_result(message, text_length, remaining_uses=remaining_uses)

    async def detect(self, text: str, timeout: float = 60.0) -> dict:
        text = text or ""
        text_len = len(text)
        if text_len < 350:
            return self._failure(f"文本长度不足 ({text_len}<350字), 请提供更长的文本", text_len)

        try:
            creds = self.load_credentials(refresh=True)
        except RuntimeError as exc:
            return await self._detect_with_page(
                text,
                timeout,
                reason=f"未找到可用 token，尝试使用朱雀页面未登录免费次数: {exc}",
            )
        if not creds.get("access_token"):
            return await self._detect_with_page(
                text,
                timeout,
                reason="朱雀凭证缺少 access_token，尝试使用真实页面未登录免费次数",
            )
        auth_payload = {"access_token": creds.get("access_token")} if creds.get("access_token") else {"fp": creds.get("fp") or _generate_fp()}
        headers = self._ws_headers(creds)
        deadline = time.time() + timeout
        text_sent = False
        # Match the current Zhuque frontend loadErrorCallback(): callback() receives
        # errorCode/errorMessage, but only ticket/randstr are sent to the WebSocket.
        captcha_payload = {
            "ticket": f"terror_1001_2089775896_{int(time.time())}",
            "randstr": "@" + "".join(random.choices(string.ascii_lowercase + string.digits, k=11)),
        }

        ws = await self._connect(headers)
        captcha_sent = False
        try:
            await ws.send(json.dumps(auth_payload, ensure_ascii=False))

            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if self.debug:
                    print(f"[zhuque:ws] {data}")

                if data.get("access_token"):
                    # 服务端刷新 token 时按朱雀前端逻辑回传一次 access_token。
                    creds["access_token"] = data["access_token"]
                    await ws.send(json.dumps({"access_token": data["access_token"]}, ensure_ascii=False))

                status = data.get("status")
                if status == "success" and data.get("confidence") is not None:
                    return normalize_zhuque_result(data, text_length=text_len, source="websocket")
                if status == "success" and data.get("data"):
                    result_data = data["data"]
                    if isinstance(result_data, str):
                        result_data = json.loads(result_data)
                    return normalize_zhuque_result(result_data, text_length=text_len, source="websocket")
                if status == "running" and data.get("cos"):
                    return await self._poll_cos_result(
                        data["cos"],
                        int(time.time() * 1000),
                        text_len,
                        creds,
                        max(1.0, deadline - time.time()),
                    )
                if status == "reauth":
                    return self._failure("朱雀登录已过期，请重新微信扫码登录", text_len)
                if status == "limited":
                    return self._failure("朱雀检测次数已用完，请切换微信账号或等待次数恢复", text_len, remaining_uses=0)
                if status == "failed":
                    return self._failure(data.get("msg") or "朱雀检测失败", text_len, remaining_uses=data.get("availableUses", -1))
                if status == "waiting":
                    continue
                if data.get("code"):
                    if str(data.get("code")) == "1" and str(data.get("evil_level")) == "0":
                        await ws.send(json.dumps({"text": text}, ensure_ascii=False))
                        text_sent = True
                        continue
                    return await self._detect_with_page(
                        text,
                        max(30.0, deadline - time.time()),
                        reason=f"验证码返回 code={data.get('code')} msg={data.get('msg') or ''}",
                    )

                # 认证完成后复刻朱雀前端 loadErrorCallback 兜底链：验证码 JS 不可用时
                # 发送 terror_1001 票据；服务端返回 code=1/evil_level=0 后再提交 text。
                if not captcha_sent and (data.get("user_name") or data.get("availableUses") is not None or data.get("access_token")):
                    await ws.send(json.dumps(captcha_payload, ensure_ascii=False))
                    captcha_sent = True
                    continue

                # 某些连接只返回用户信息/剩余次数，不返回 code；兜底直接提交 text。
                if captcha_sent and not text_sent and (data.get("user_name") or data.get("availableUses") is not None):
                    await ws.send(json.dumps({"text": text}, ensure_ascii=False))
                    text_sent = True

            return self._failure(f"检测超时 ({timeout}s), 请检查朱雀凭证或网络状态", text_len)
        finally:
            await ws.close()

    async def classify(self, text: str) -> dict:
        result = await self.detect(text)
        if not result["success"]:
            return {"verdict": "error", "detail": result["message"], "raw": result}

        ratio = result.get("labels_ratio") or {}
        ai_prob = _coerce_ratio_value(ratio.get("0"))
        human_prob = _coerce_ratio_value(ratio.get("1"))
        suspicious_prob = _coerce_ratio_value(ratio.get("2"))
        if ai_prob >= human_prob and ai_prob >= suspicious_prob:
            verdict = "AI_generated"
            label = LABEL_NAMES[0]
            confidence = ai_prob
        elif human_prob >= suspicious_prob:
            verdict = "human_written"
            label = LABEL_NAMES[1]
            confidence = human_prob
        else:
            verdict = "mixed"
            label = LABEL_NAMES[2]
            confidence = suspicious_prob

        return {
            "verdict": verdict,
            "verdict_label": label,
            "confidence": confidence,
            "detail": result.get("alert_text", ""),
            "raw": result,
        }
