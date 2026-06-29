"""
朱雀 AI 检测 API — 微信扫码凭证 + 无头 WebSocket 版。

登录链路：zhuque_pkg/capture_zhuque_creds.py 打开一次可见浏览器，微信扫码后
保存 creds_latest.json。检测链路：后端直接连接朱雀 WebSocket API，不再依赖
旧版本地页面控制 / matrix 页面 DOM。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import string
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import websockets

logger = logging.getLogger(__name__)


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

    text = str(text or "")
    if re.search(r"(-1|unknown|unavailable|检测后同步|未知|不可用)", text, re.IGNORECASE):
        return -1
    quota_patterns = [
        r"(?:今日)?剩余\s*(\d+)\s*次",
        r"可用\s*(\d+)\s*次",
        r"(\d+)\s*(?:left|uses?|次)",
        r"(?:left|uses?|remaining|available|quota)[^\d]{0,12}(\d+)",
    ]
    for pattern in quota_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    if re.fullmatch(r"\s*\d+\s*", text):
        return int(text.strip())
    match = re.search(r"(?:Detect now|立即检测)[^\d]{0,16}(\d+)", text, re.IGNORECASE)
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
    has_anonymous_fp = bool(fp) and not access_token
    remaining_uses = _coerce_remaining_uses(
        raw.get("remaining_uses"),
        raw.get("remainingUses"),
        raw.get("availableUses"),
        raw.get("quota_text"),
        raw.get("quotaText"),
    )
    if logged_out_placeholder:
        # Keep the anonymous page fingerprint for no-consume WebSocket quota
        # probes. It is not a logged-in credential, so never reuse the static
        # page quota from this snapshot as an account quota.
        cookies = ""
        remaining_uses = -1

    return {
        "access_token": access_token,
        "fp": fp,
        "has_anonymous_fp": has_anonymous_fp,
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


def _decode_zhuque_json_payload(payload: Any) -> Optional[dict]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(payload, str):
        return None
    try:
        decoded = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _extract_zhuque_terminal_payload(payload: Any) -> Optional[dict]:
    """Extract the real Zhuque detect result payload from observed envelopes.

    Confirmed Zhuque frontend flow:
    - WebSocket terminal frame can be `{"status":"success", ...result...}`.
    - Running frame stores `cos`; the page polls `/user/detect/result` and then
      calls `getRst(e.data.data)`, where `data` is the JSON string containing
      `confidence`, `labels_ratio`, and `segment_labels`.
    """
    data = _decode_zhuque_json_payload(payload)
    if not data:
        return None

    status = str(data.get("status") or "").strip().lower()
    if status == "success" and data.get("confidence") is not None:
        return data

    if status == "success" and data.get("data"):
        return _decode_zhuque_json_payload(data.get("data"))

    if data.get("success") is True and data.get("data"):
        return _decode_zhuque_json_payload(data.get("data"))

    if data.get("confidence") is not None and (
        data.get("labels_ratio") is not None
        or data.get("labelsRatio") is not None
        or data.get("segment_labels") is not None
    ):
        return data

    if isinstance(data.get("segment_labels"), list):
        return data

    return None


def _zhuque_payload_has_segment_labels(payload: Any) -> bool:
    data = payload if isinstance(payload, dict) else None
    labels = data.get("segment_labels") if data else None
    return isinstance(labels, list) and len(labels) > 0


def _merge_zhuque_page_payload(*, observed_payloads: list[dict], vue: dict, page_state: dict) -> dict:
    payload = next(
        (item for item in reversed(observed_payloads) if _zhuque_payload_has_segment_labels(item)),
        None,
    )
    if payload is None and observed_payloads:
        payload = observed_payloads[-1]
    if not isinstance(payload, dict):
        payload = {}
    payload = dict(payload)
    payload.update({
        "confidence": vue.get("rate"),
        "rateLabel": vue.get("rateLabel"),
        "labelsRatio": vue.get("labelsRatio") or {},
        "msg": vue.get("msg") or "",
        "alert_text": (page_state.get("alert") or "").replace("Report", "").replace("下载报告", "").strip(),
        "alert_title": page_state.get("alert_title") or "",
        "availableUses": _parse_remaining_uses(page_state.get("button_text") or ""),
    })
    return payload


def parse_zhuque_websocket_result(payload: str, text_length: int) -> Optional[dict]:
    """Parse a terminal Zhuque WebSocket result frame into the public result shape.

    GankAIGC 内部契约固定为：0=AI，1=人工，2=疑似/混合。
    朱雀网页历史结果里有过 0/1 语义切换，因此这里会用 confidence/rate 做一次
    归一化，避免把人工占比错当 AI 风险。
    """
    data = _extract_zhuque_terminal_payload(payload)
    if not data:
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
        # Live Zhuque payloads expose position as [start, length]. Preserve the
        # original field and add explicit metadata for downstream debugging.
        position = cloned.get("position")
        if (
            isinstance(position, list)
            and len(position) == 2
            and all(isinstance(value, (int, float)) for value in position)
        ):
            start = int(position[0])
            length = int(position[1])
            if start >= 0 and length > 0:
                cloned["position_format"] = "start_length"
                cloned["position_start"] = start
                cloned["position_length"] = length
                cloned["position_end"] = start + length
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
        session_status = self._read_session_status()
        if (
            session_status
            and session_status.get("connected") is False
            and not session_status.get("has_token")
        ):
            anonymous_creds = self._load_anonymous_credentials()
            if anonymous_creds:
                self._credentials_cache = anonymous_creds
                return dict(anonymous_creds)
            raise RuntimeError("朱雀网页显示未登录")
        if not self.credentials_file.exists():
            anonymous_creds = self._load_anonymous_credentials()
            if anonymous_creds:
                self._credentials_cache = anonymous_creds
                return dict(anonymous_creds)
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
            anonymous_creds = self._load_anonymous_credentials()
            if anonymous_creds:
                self._credentials_cache = anonymous_creds
                return dict(anonymous_creds)
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

    def _local_storage_from_browser_state(self, browser_state: dict) -> dict:
        if not isinstance(browser_state, dict):
            return {}
        direct = browser_state.get("localStorage") or browser_state.get("local_storage")
        if isinstance(direct, dict):
            return direct
        origins = browser_state.get("origins")
        if isinstance(origins, list):
            for origin in origins:
                if not isinstance(origin, dict):
                    continue
                origin_name = str(origin.get("origin") or "")
                storage_items = origin.get("localStorage") or origin.get("local_storage")
                if "matrix.tencent.com" not in origin_name and not storage_items:
                    continue
                if isinstance(storage_items, list):
                    values = {
                        str(item.get("name")): str(item.get("value") or "")
                        for item in storage_items
                        if isinstance(item, dict) and item.get("name")
                    }
                    if values:
                        return values
                if isinstance(storage_items, dict):
                    return storage_items
        return {}

    def _token_from_local_storage(self, local_storage: dict) -> str:
        if not isinstance(local_storage, dict):
            return ""
        for key in ("aiGenAccessToken", "access_token", "accessToken", "token", "authToken"):
            token = _unwrap_token_value(local_storage.get(key))
            if token:
                return token
        for key, value in local_storage.items():
            lower_key = str(key).lower()
            if "token" in lower_key and ("access" in lower_key or "auth" in lower_key):
                token = _unwrap_token_value(value)
                if token:
                    return token
        return ""

    def _anonymous_fp_from_browser_state_file(self, state_file: Path) -> str:
        if not state_file.exists():
            return ""
        try:
            browser_state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if _unwrap_token_value(browser_state.get("access_token")):
            return ""
        local_storage = self._local_storage_from_browser_state(browser_state)
        if self._token_from_local_storage(local_storage):
            return ""
        raw_cookies = browser_state.get("cookies") or []
        if isinstance(raw_cookies, list):
            for cookie in raw_cookies:
                if not isinstance(cookie, dict) or not cookie.get("value"):
                    continue
                cookie_name = str(cookie.get("name") or "").lower()
                if "token" in cookie_name and ("access" in cookie_name or "auth" in cookie_name):
                    return ""
        elif isinstance(raw_cookies, str):
            cookie_text = raw_cookies.lower()
            if "access_token=" in cookie_text or "accesstoken=" in cookie_text or "auth_token=" in cookie_text:
                return ""
        return str(local_storage.get("fp") or "").strip()

    def _legacy_browser_state_file(self) -> Path:
        return _default_credentials_file().parent / "browser_state.json"

    def _load_anonymous_credentials(self) -> Optional[dict]:
        """Load a persisted logged-out fingerprint for anonymous quota peeks.

        The anonymous fp is not a logged-in credential. It may be persisted by
        the real-page sync/logout path in session_status.json, or recovered from
        a browser_state.json that has no access token. Static quota numbers from
        these snapshots are intentionally ignored; live WebSocket/page probes own
        freshness.
        """
        status = self._read_session_status() or {}
        status_has_token = bool(status.get("has_token"))
        status_connected = bool(status.get("connected") or status.get("ready"))
        fp = ""
        if not status_has_token and not status_connected:
            fp = str(status.get("anonymous_fp") or status.get("fp") or "").strip()

        if not fp:
            state_file = self.credentials_file.parent / "browser_state.json"
            fp = self._anonymous_fp_from_browser_state_file(state_file)

        if not fp and self.credentials_file.exists():
            try:
                raw_credentials = json.loads(self.credentials_file.read_text(encoding="utf-8"))
                candidate_creds = _extract_credentials(raw_credentials)
            except (OSError, json.JSONDecodeError):
                candidate_creds = {}
            if not candidate_creds.get("access_token"):
                fp = str(candidate_creds.get("fp") or "").strip()

        if not fp:
            return None
        return {
            "access_token": "",
            "fp": fp,
            "has_anonymous_fp": True,
            "cookies": "",
            "user_name": "",
            "quota_text": "",
            "remaining_uses": -1,
            "captured_at": status.get("updated_at") or "",
            "raw": {"anonymous_fp": fp, "source": "session_status"},
        }

    def _browser_state_has_matrix_local_storage(self, state_file: Path) -> bool:
        """Return whether a saved Playwright state can initialize Zhuque identity."""
        if not state_file.exists():
            return False
        try:
            browser_state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(self._local_storage_from_browser_state(browser_state))

    def _anonymous_page_storage_state(self) -> Optional[dict]:
        """Build a token-free Playwright storage state for anonymous quota probes."""
        state_file = self.credentials_file.parent / "browser_state.json"
        legacy_state_file = self._legacy_browser_state_file()
        fp = self._anonymous_fp_from_browser_state_file(state_file)
        if not fp:
            anonymous_creds = self._load_anonymous_credentials()
            if anonymous_creds and not anonymous_creds.get("access_token"):
                fp = str(anonymous_creds.get("fp") or "").strip()
        if not fp and legacy_state_file != state_file:
            fp = self._anonymous_fp_from_browser_state_file(legacy_state_file)
        if not fp:
            return None
        return {
            "cookies": [],
            "origins": [
                {
                    "origin": self.http_base_url,
                    "localStorage": [
                        {"name": "fp", "value": fp},
                        {"name": "language", "value": "en"},
                    ],
                }
            ],
        }

    def _status_from_session_file(self, status: dict) -> dict:
        connected = bool(status.get("connected") or status.get("ready"))
        remaining_uses = _coerce_remaining_uses(status.get("remaining_uses"), status.get("quota_text"))
        has_anonymous_fp = bool(status.get("has_anonymous_fp") or status.get("anonymous_fp") or status.get("fp"))
        return {
            "ready": connected,
            "connected": connected,
            "page_found": connected,
            "has_token": bool(status.get("has_token")) if connected else False,
            "has_anonymous_fp": has_anonymous_fp,
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
                "has_anonymous_fp": False,
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
        has_anonymous_fp = bool(creds.get("has_anonymous_fp") or (creds.get("fp") and not has_token))
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
            "has_anonymous_fp": has_anonymous_fp,
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

    def _quota_probe_artifact_paths(self) -> tuple[Path, Path]:
        base = self.credentials_file.parent
        return base / "quota_probe_latest.txt", base / "quota_probe_latest.png"

    async def _write_quota_probe_artifacts(self, page, *, reason: str, quota_state: dict | None = None) -> None:
        """Persist non-secret probe evidence for local troubleshooting.

        The anonymous quota probe does not persist cookies/tokens. It stores the
        visible page text and a screenshot only when parsing fails, so we can see
        whether Tencent changed DOM text, blocked rendering, or hid the quota.
        """
        try:
            text_file, screenshot_file = self._quota_probe_artifact_paths()
            text_file.parent.mkdir(parents=True, exist_ok=True)
            body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            payload = {
                "reason": reason,
                "url": page.url,
                "title": await page.title(),
                "quota_state": quota_state or {},
                "body_text": body_text[:12000],
            }
            text_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            await page.screenshot(path=str(screenshot_file), full_page=True)
        except Exception:
            logger.debug("Failed to persist Zhuque quota probe artifacts", exc_info=True)

    async def _peek_quota_status_with_page(self, timeout: float = 5.0) -> dict:
        """Read anonymous/free quota state from the real Zhuque page.

        Logged-in quota is usually captured with credentials, but after the VPS
        remote-QR flow there is no long-lived local Chrome window to mirror the
        logged-out page. This method opens a hidden Chromium page, inspects the
        same Vue state and submit button the real UI uses, and never clicks the
        Detect button, so it does not consume a Zhuque detection.
        """
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {
                "remaining_uses": -1,
                "button_enabled": False,
                "page_found": False,
                "quota_text": "",
                "message": f"Playwright 不可用，无法打开朱雀页面探测免费次数: {exc}",
            }

        state_file = self.credentials_file.parent / "browser_state.json"

        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self._playwright_browsers_path()))
        pw = None
        browser = None
        last_state: dict = {}
        try:
            pw = await async_playwright().start()
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
            anonymous_storage_state = self._anonymous_page_storage_state()
            if anonymous_storage_state:
                ctx_kwargs["storage_state"] = anonymous_storage_state
            ctx = await browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()
            page_timeout_ms = int(max(timeout, 5.0) * 1000)
            await page.goto(f"{self.http_base_url}/ai-detect/", wait_until="domcontentloaded", timeout=page_timeout_ms)
            await page.wait_for_timeout(1200)

            async def collect_quota_state() -> dict:
                return await page.evaluate(
                    r"""() => {
                        const candidates = [];
                        const vueSignals = [];
                        const pushCandidate = (value, source) => {
                            if (value === undefined || value === null || typeof value === 'boolean') return;
                            const text = String(value).replace(/\s+/g, ' ').trim();
                            if (!text) return;
                            const item = { value: text, source: String(source || '') };
                            if (!candidates.some((x) => x.value === item.value && x.source === item.source)) candidates.push(item);
                        };
                        const pushSignal = (key, value, source) => {
                            if (value === undefined || value === null || typeof value === 'function') return;
                            const text = typeof value === 'object' ? '[object]' : String(value).replace(/\s+/g, ' ').trim();
                            vueSignals.push({ key: String(key || ''), value: text, source: String(source || '') });
                        };
                        const maybeQuotaText = (text) => (
                            /(\d+\s*(left|次)|今日剩余|剩余|可用|remaining|available|quota|uses?)/i.test(text || '')
                        );
                        const quotaKey = (key) => (
                            /^(aiGenTxtRemainingCount|availableUses|available_uses|remainingUses|remaining_uses|quotaText|quota_text|available|quota|left)$/i.test(key || '')
                        );
                        const walkObject = (obj, source, depth = 0, seen = new Set()) => {
                            if (!obj || depth > 3 || seen.has(obj)) return;
                            seen.add(obj);
                            for (const key of Object.keys(obj)) {
                                let value;
                                try { value = obj[key]; } catch (_) { continue; }
                                const keyText = String(key || '');
                                const keyLooksLikeQuota = quotaKey(keyText);
                                const keyIsExtraAttemptCounter = /^remainingRequests$/i.test(keyText);
                                if (typeof value === 'string' || typeof value === 'number') {
                                    if (keyLooksLikeQuota) pushCandidate(value, `${source}.${keyText}`);
                                    else if (keyIsExtraAttemptCounter) pushSignal(keyText, value, source);
                                    else if (maybeQuotaText(String(value))) pushCandidate(value, `${source}.${keyText}`);
                                    continue;
                                }
                                if (value && typeof value === 'object') {
                                    if (keyLooksLikeQuota || /remain|remaining|available|quota|uses?|left/i.test(keyText)) {
                                        pushSignal(keyText, value, source);
                                        walkObject(value, `${source}.${keyText}`, depth + 1, seen);
                                    }
                                }
                            }
                        };
                        const selectorList = [
                            '.submit-btn',
                            '.detect-btn',
                            '.quota',
                            '.quota-text',
                            '[class*="quota"]',
                            '[class*="remain"]',
                            '[class*="usage"]'
                        ];
                        for (const selector of selectorList) {
                            document.querySelectorAll(selector).forEach((el) => {
                                const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                                if (maybeQuotaText(text)) pushCandidate(text, selector);
                            });
                        }
                        const submitBtn = document.querySelector('.submit-btn')
                            || [...document.querySelectorAll('button')].find((button) => /Detect|检测/i.test(button.textContent || ''));
                        const submitButtonText = submitBtn ? (submitBtn.textContent || '').replace(/\s+/g, ' ').trim() : '';
                        const submitButtonVisible = !!submitBtn && !!(submitBtn.offsetWidth || submitBtn.offsetHeight || submitBtn.getClientRects().length);
                        const submitButtonDisabled = !!submitBtn && (
                            submitBtn.disabled
                            || submitBtn.classList.contains('is-disabled')
                            || submitBtn.getAttribute('aria-disabled') === 'true'
                        );
                        if (submitButtonText && maybeQuotaText(submitButtonText)) pushCandidate(submitButtonText, 'submitButtonText');
                        document.querySelectorAll('button').forEach((button) => {
                            const text = (button.textContent || '').replace(/\s+/g, ' ').trim();
                            if (/Detect|检测|剩余|left|remain|quota|次|uses?/i.test(text) && maybeQuotaText(text)) {
                                pushCandidate(text, 'button');
                            }
                        });
                        document.querySelectorAll('*').forEach((el, index) => {
                            const text = (el.textContent || '').trim();
                            if (text.length <= 120 && maybeQuotaText(text)) pushCandidate(text, `node:${index}`);
                            if (el.__vue__) walkObject(el.__vue__, `vue:${index}`);
                            if (el.__vueParentComponent) {
                                walkObject(el.__vueParentComponent.props, `vue3:${index}.props`);
                                walkObject(el.__vueParentComponent.setupState, `vue3:${index}.setupState`);
                                walkObject(el.__vueParentComponent.ctx, `vue3:${index}.ctx`);
                            }
                        });
                        if (document.body) {
                            document.body.innerText
                                .split(/\n+/)
                                .map((line) => line.trim())
                                .filter((line) => line.length <= 120 && maybeQuotaText(line))
                                .forEach((line) => pushCandidate(line, 'body'));
                        }
                        const textHostFound = !!document.querySelector('.el-textarea__inner, textarea, [contenteditable="true"]')
                            || [...document.querySelectorAll('*')].some((el) => el.__vue__ && Object.prototype.hasOwnProperty.call(el.__vue__, 'text'));
                        let anonymousFp = '';
                        try {
                            anonymousFp = (localStorage.getItem('fp') || '').trim();
                        } catch (_) {
                            anonymousFp = '';
                        }
                        return {
                            quota_texts: candidates.slice(0, 48).map((item) => item.value),
                            quota_sources: candidates.slice(0, 48),
                            vue_signals: vueSignals.slice(0, 48),
                            fp: anonymousFp,
                            anonymous_fp: anonymousFp,
                            has_anonymous_fp: Boolean(anonymousFp),
                            submit_button_text: submitButtonText,
                            button_enabled: Boolean(submitBtn && submitButtonVisible && !submitButtonDisabled && /Detect|检测/i.test(submitButtonText || 'Detect')),
                            page_found: Boolean(document.body),
                            text_host_found: textHostFound,
                            body_preview: document.body ? document.body.innerText.slice(0, 1000) : '',
                        };
                    }"""
                )

            async def fill_probe_text() -> str:
                return await page.evaluate(
                    r"""async (text) => {
                        const results = [];
                        const setElementText = (el) => {
                            if (!el) return false;
                            if ('value' in el) {
                                const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                                if (setter) setter.call(el, text);
                                else el.value = text;
                            } else {
                                el.textContent = text;
                            }
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        };
                        const textEl = document.querySelector('.el-textarea__inner, textarea, [contenteditable="true"]');
                        if (setElementText(textEl)) results.push('SET_ELEMENT');
                        const vueHosts = [...document.querySelectorAll('*')]
                            .filter((el) => el.__vue__ && Object.prototype.hasOwnProperty.call(el.__vue__, 'text'));
                        for (const host of vueHosts) {
                            const vm = host.__vue__;
                            try {
                                vm.text = text;
                                results.push('SET_VUE_TEXT');
                                if (typeof vm.$forceUpdate === 'function') vm.$forceUpdate();
                                if (typeof vm.$nextTick === 'function') {
                                    await new Promise((resolve) => vm.$nextTick(resolve));
                                }
                                if (typeof vm.getInitialRemainingCount === 'function') {
                                    const maybePromise = vm.getInitialRemainingCount();
                                    if (maybePromise && typeof maybePromise.then === 'function') {
                                        await Promise.race([maybePromise.catch(() => null), new Promise((resolve) => setTimeout(resolve, 800))]);
                                    }
                                    results.push('CALL_getInitialRemainingCount');
                                }
                            } catch (error) {
                                results.push('VUE_ERROR:' + (error && error.message ? error.message : String(error)));
                            }
                        }
                        return results.join('|') || 'NO_TEXT_HOST';
                    }""",
                    "朱雀免费次数探测文本。" * 80,
                )

            deadline = time.time() + max(timeout, 1.0)
            probe_text_filled = False
            while time.time() < deadline:
                last_state = await collect_quota_state()
                remaining_uses = _coerce_remaining_uses(*(last_state.get("quota_texts") or []))
                if remaining_uses >= 0:
                    return {
                        "remaining_uses": remaining_uses,
                        "button_enabled": remaining_uses > 0,
                        "page_found": bool(last_state.get("page_found")),
                        "quota_text": " | ".join(last_state.get("quota_texts") or []),
                        "fp": str(last_state.get("fp") or "").strip(),
                        "anonymous_fp": str(last_state.get("anonymous_fp") or last_state.get("fp") or "").strip(),
                        "has_anonymous_fp": bool(last_state.get("has_anonymous_fp") or last_state.get("anonymous_fp") or last_state.get("fp")),
                        "probe_state": last_state,
                        "message": "朱雀页面剩余次数已解析",
                    }
                if not probe_text_filled:
                    probe_text_filled = True
                    last_state["fill_result"] = await fill_probe_text()
                    await page.wait_for_timeout(1200)
                    continue
                if last_state.get("button_enabled"):
                    return {
                        "remaining_uses": -1,
                        "button_enabled": True,
                        "page_found": bool(last_state.get("page_found")),
                        "quota_text": last_state.get("submit_button_text") or "Detect now",
                        "fp": str(last_state.get("fp") or "").strip(),
                        "anonymous_fp": str(last_state.get("anonymous_fp") or last_state.get("fp") or "").strip(),
                        "has_anonymous_fp": bool(last_state.get("has_anonymous_fp") or last_state.get("anonymous_fp") or last_state.get("fp")),
                        "probe_state": last_state,
                        "message": "朱雀页面检测入口可用，但当前页面未暴露剩余次数数字",
                    }
                await page.wait_for_timeout(500)

            await self._write_quota_probe_artifacts(page, reason="quota_not_found", quota_state=last_state)
            return {
                "remaining_uses": -1,
                "button_enabled": bool(last_state.get("button_enabled")),
                "page_found": bool(last_state.get("page_found")),
                "quota_text": last_state.get("submit_button_text") or "",
                "fp": str(last_state.get("fp") or "").strip(),
                "anonymous_fp": str(last_state.get("anonymous_fp") or last_state.get("fp") or "").strip(),
                "has_anonymous_fp": bool(last_state.get("has_anonymous_fp") or last_state.get("anonymous_fp") or last_state.get("fp")),
                "probe_state": last_state,
                "message": "朱雀页面未暴露剩余次数数字",
            }
        except Exception as exc:
            logger.warning(
                "[ZhuqueAPI] anonymous quota page probe failed | credential_dir=%s | error=%s",
                self.credentials_file.parent,
                exc,
                exc_info=True,
            )
            return {
                "remaining_uses": -1,
                "button_enabled": False,
                "page_found": False,
                "quota_text": "",
                "message": f"朱雀页面探测失败: {exc}",
            }
        finally:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.close()
            if pw is not None:
                with contextlib.suppress(Exception):
                    await pw.stop()

    async def _peek_remaining_uses_with_page(self, timeout: float = 5.0) -> Optional[int]:
        """Compatibility wrapper returning only a known numeric anonymous quota."""
        status = await self._peek_quota_status_with_page(timeout=timeout)
        remaining_uses = _coerce_remaining_uses(status.get("remaining_uses"), status.get("quota_text"))
        return remaining_uses if remaining_uses >= 0 else None

    async def peek_quota_status(self, timeout: float = 3.0, *, allow_anonymous: bool = False) -> dict:
        """Return live quota state, preserving button availability when count is hidden."""
        creds = None
        if allow_anonymous:
            try:
                creds = self.load_credentials(refresh=True)
            except RuntimeError:
                return await self._peek_quota_status_with_page(timeout=timeout)
            if not creds.get("access_token") and not creds.get("fp"):
                return await self._peek_quota_status_with_page(timeout=timeout)
        remaining_uses = await self.peek_remaining_uses(timeout=timeout, allow_anonymous=allow_anonymous)
        remaining_uses = _coerce_remaining_uses(remaining_uses)
        if allow_anonymous and remaining_uses < 0 and creds and not creds.get("access_token"):
            return await self._peek_quota_status_with_page(timeout=timeout)
        return {
            "remaining_uses": remaining_uses,
            "button_enabled": remaining_uses > 0 if remaining_uses >= 0 else False,
            "page_found": remaining_uses >= 0,
            "quota_text": f"剩余 {remaining_uses} 次" if remaining_uses >= 0 else "",
            "fp": str(creds.get("fp") or "").strip() if creds and not creds.get("access_token") else "",
            "anonymous_fp": str(creds.get("fp") or "").strip() if creds and not creds.get("access_token") else "",
            "has_anonymous_fp": bool(creds and creds.get("fp") and not creds.get("access_token")),
            "message": "朱雀剩余次数已同步" if remaining_uses >= 0 else "暂未探测到朱雀剩余次数",
        }

    async def peek_remaining_uses(self, timeout: float = 3.0, *, allow_anonymous: bool = False) -> Optional[int]:
        """Read live Zhuque quota from the initial WebSocket auth frames.

        This sends only the saved access token/fp and closes the connection before
        captcha/text submission, so it does not consume a detection use.
        """
        try:
            creds = self.load_credentials(refresh=True)
        except RuntimeError:
            if allow_anonymous:
                return await self._peek_remaining_uses_with_page(timeout=timeout)
            return None
        if not creds.get("access_token") and not creds.get("fp"):
            if allow_anonymous:
                return await self._peek_remaining_uses_with_page(timeout=timeout)
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

    async def _detect_with_page(self, text: str, timeout: float, *, reason: str = "", anonymous: bool = False) -> dict:
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
            if anonymous:
                anonymous_storage_state = self._anonymous_page_storage_state()
                if anonymous_storage_state:
                    ctx_kwargs["storage_state"] = anonymous_storage_state
            elif state_file.exists():
                ctx_kwargs["storage_state"] = str(state_file)
            ctx = await browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()
            observed_result_payloads: list[dict] = []

            def remember_result_payload(payload: Any) -> None:
                result_payload = _extract_zhuque_terminal_payload(payload)
                if not result_payload:
                    return
                observed_result_payloads.append(result_payload)
                if len(observed_result_payloads) > 20:
                    del observed_result_payloads[:-20]

            def on_websocket(ws) -> None:
                ws.on("framereceived", remember_result_payload)

            async def on_response(response) -> None:
                if "/user/detect/result" not in response.url:
                    return
                with contextlib.suppress(Exception):
                    remember_result_payload(await response.text())

            page.on("websocket", on_websocket)
            page.on("response", lambda response: asyncio.create_task(on_response(response)))
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
                r"""async (text) => {
                    const results = [];
                    const setElementText = (el) => {
                        if (!el) return false;
                        if ('value' in el) {
                            const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                            if (setter) setter.call(el, text);
                            else el.value = text;
                        } else {
                            el.textContent = text;
                        }
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    };
                    const textEl = document.querySelector('.el-textarea__inner, textarea, [contenteditable="true"]');
                    if (setElementText(textEl)) results.push('SET_ELEMENT');
                    const vueHosts = [...document.querySelectorAll('*')]
                        .filter((el) => el.__vue__ && Object.prototype.hasOwnProperty.call(el.__vue__, 'text'));
                    for (const host of vueHosts) {
                        const vm = host.__vue__;
                        try {
                            vm.text = text;
                            results.push('SET_VUE_TEXT');
                            if (typeof vm.$forceUpdate === 'function') vm.$forceUpdate();
                            if (typeof vm.$nextTick === 'function') {
                                await new Promise((resolve) => vm.$nextTick(resolve));
                            }
                        } catch (error) {
                            results.push('VUE_ERROR:' + (error && error.message ? error.message : String(error)));
                        }
                    }
                    return results.join('|') || 'NO_TEXT_HOST';
                }""",
                text,
            )
            if "NO_TEXT_HOST" in str(set_result):
                await self._write_quota_probe_artifacts(page, reason="detect_text_host_not_found", quota_state={"set_result": str(set_result)})
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
                        const payloads = [];
                        const pushPayload = (value, source) => {
                            if (!value || typeof value !== 'object') return;
                            const hasScore = value.confidence !== undefined || value.rate !== undefined || value.ai_generated !== undefined;
                            const hasLabels = value.labels_ratio !== undefined || value.labelsRatio !== undefined;
                            const hasSegments = Array.isArray(value.segment_labels);
                            if (!hasScore && !hasLabels && !hasSegments) return;
                            const cleanSegmentLabels = (items) => {
                                if (!Array.isArray(items)) return undefined;
                                return items
                                    .filter((item) => item && typeof item === 'object')
                                    .map((item) => ({
                                        text: item.text,
                                        label: item.label,
                                        conf: item.conf,
                                        order: item.order,
                                        position: Array.isArray(item.position) ? item.position.slice(0, 2) : item.position
                                    }));
                            };
                            const cleanValue = {
                                confidence: value.confidence,
                                rate: value.rate,
                                ai_generated: value.ai_generated,
                                rateLabel: value.rateLabel,
                                rate_label: value.rate_label,
                                labels_ratio: value.labels_ratio,
                                labelsRatio: value.labelsRatio,
                                msg: value.msg,
                                message: value.message,
                                availableUses: value.availableUses,
                                remainingUses: value.remainingUses,
                                remaining_uses: value.remaining_uses,
                                content_type: value.content_type,
                                feedback_token: value.feedback_token,
                                segment_labels: cleanSegmentLabels(value.segment_labels)
                            };
                            Object.keys(cleanValue).forEach((key) => cleanValue[key] === undefined && delete cleanValue[key]);
                            payloads.push({ source, value: cleanValue });
                        };
                        const pushKnownVuePayloads = (vm, source) => {
                            if (!vm || typeof vm !== 'object') return;
                            try { pushPayload(vm.data, `${source}.data`); } catch (_) {}
                            try {
                                if (Array.isArray(vm.segmentLabel)) {
                                    pushPayload({ segment_labels: vm.segmentLabel }, `${source}.segmentLabel`);
                                }
                            } catch (_) {}
                            try {
                                if (Array.isArray(vm.segmentLabels)) {
                                    pushPayload({ segment_labels: vm.segmentLabels }, `${source}.segmentLabels`);
                                }
                            } catch (_) {}
                            try {
                                if (vm.data && Array.isArray(vm.data.segment_labels)) {
                                    pushPayload(vm.data, `${source}.data.segment_labels`);
                                }
                            } catch (_) {}
                        };
                        const walkForPayloads = (obj, source, depth = 0, seen = new Set()) => {
                            if (!obj || typeof obj !== 'object' || depth > 4 || seen.has(obj)) return;
                            seen.add(obj);
                            pushPayload(obj, source);
                            for (const key of Object.keys(obj)) {
                                if (![
                                    'data',
                                    'segmentLabel',
                                    'segmentLabels',
                                    'segment_labels',
                                    'props',
                                    'setupState',
                                    'ctx',
                                    '$props',
                                    '$data',
                                    '$parent'
                                ].includes(key)) continue;
                                let value;
                                try { value = obj[key]; } catch (_) { continue; }
                                if (Array.isArray(value) && key !== 'segment_labels') {
                                    pushPayload({ segment_labels: value }, `${source}.${key}`);
                                } else if (value && typeof value === 'object') {
                                    walkForPayloads(value, `${source}.${key}`, depth + 1, seen);
                                }
                            }
                        };
                        let anonymousFp = '';
                        try {
                            anonymousFp = (localStorage.getItem('fp') || '').trim();
                        } catch (_) {
                            anonymousFp = '';
                        }
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
                        document.querySelectorAll('*').forEach((node, index) => {
                            if (node.__vue__) {
                                pushKnownVuePayloads(node.__vue__, `vue:${index}`);
                                walkForPayloads(node.__vue__, `vue:${index}`);
                            }
                            if (node.__vueParentComponent) {
                                pushKnownVuePayloads(node.__vueParentComponent.props, `vue3:${index}.props`);
                                pushKnownVuePayloads(node.__vueParentComponent.setupState, `vue3:${index}.setupState`);
                                pushKnownVuePayloads(node.__vueParentComponent.ctx, `vue3:${index}.ctx`);
                                walkForPayloads(node.__vueParentComponent.props, `vue3:${index}.props`);
                                walkForPayloads(node.__vueParentComponent.setupState, `vue3:${index}.setupState`);
                                walkForPayloads(node.__vueParentComponent.ctx, `vue3:${index}.ctx`);
                            }
                        });
                        return {
                            vue,
                            result_payloads: payloads
                                .sort((left, right) => {
                                    const leftHasSegments = Array.isArray(left.value.segment_labels) && left.value.segment_labels.length > 0;
                                    const rightHasSegments = Array.isArray(right.value.segment_labels) && right.value.segment_labels.length > 0;
                                    return Number(rightHasSegments) - Number(leftHasSegments);
                                })
                                .slice(0, 8),
                            alert: alert ? alert.textContent.trim() : '',
                            alert_title: title ? title.textContent.trim() : '',
                            button_text: btn ? btn.textContent.trim() : '',
                            fp: anonymousFp,
                            anonymous_fp: anonymousFp
                        };
                    }"""
                )
                for observed in data.get("result_payloads") or []:
                    if isinstance(observed, dict):
                        remember_result_payload(observed.get("value"))
                vue = data.get("vue") or {}
                if vue.get("type") and not vue.get("processing") and vue.get("rate") is not None:
                    payload = _merge_zhuque_page_payload(
                        observed_payloads=observed_result_payloads,
                        vue=vue,
                        page_state=data,
                    )
                    result = normalize_zhuque_result(payload, text_length=len(text), source="page_fallback")
                    result["page_result_payload_count"] = len(observed_result_payloads)
                    result["page_result_has_segment_labels"] = any(
                        _zhuque_payload_has_segment_labels(item) for item in observed_result_payloads
                    )
                    anonymous_fp = str(data.get("anonymous_fp") or data.get("fp") or "").strip()
                    if anonymous and anonymous_fp:
                        result.update(
                            {
                                "fp": anonymous_fp,
                                "anonymous_fp": anonymous_fp,
                                "has_anonymous_fp": True,
                            }
                        )
                    return result

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
                anonymous=True,
            )
        if not creds.get("access_token"):
            return await self._detect_with_page(
                text,
                timeout,
                reason="朱雀凭证缺少 access_token，尝试使用真实页面未登录免费次数",
                anonymous=True,
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
