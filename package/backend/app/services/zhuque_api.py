"""
朱雀 AI 检测 API — 本机可见浏览器状态 + WebSocket/API 检测。

本机/一键包链路会打开或复用系统 Chrome/Edge/Brave 的朱雀页面，
凭证和页面状态默认保存在 package/data/zhuque/users 或 ZHUQUE_USER_DATA_DIR。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import subprocess
import time
import urllib.error
import urllib.request
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


def _captcha_required_zhuque_result(message: str, text_length: int, *, source: str = "page_fallback") -> dict:
    result = _failure_zhuque_result(message, text_length, source=source)
    result.update(
        {
            "error_code": "zhuque_captcha_required",
            "manual_verification_required": True,
            "manual_verification_mode": "local_window",
            "manual_verification_action": "open_zhuque_local_window",
            "manual_verification_label": "打开朱雀验证窗口",
        }
    )
    return result


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


def _looks_like_zhuque_account_name(text: str) -> bool:
    text = str(text or "").strip()
    if not text or len(text) > 24 or _is_login_prompt_text(text):
        return False
    if _parse_remaining_uses(text) >= 0:
        return False
    ignored = {
        "zhuque ai detection assistant",
        "ai detection assistant",
        "free ai detection assistant",
        "text",
        "image/video",
        "upload",
        "clear",
        "detect",
        "detecting",
        "important notice",
        "notice",
        "invited tester",
        "aigc text",
        "aigc image",
    }
    normalised = re.sub(r"\s+", " ", text).strip().lower()
    if normalised in ignored:
        return False
    if re.search(r"detect|notice|assistant|upload|clear|model update|copyright|tencent|^aigc\s+(text|image)$", text, re.IGNORECASE):
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", text))


def _extract_account_name_from_body_preview(text: str) -> str:
    """Recover Zhuque header account text from the top of body.innerText.

    The live page may expose the nickname as a standalone early line, for
    example: logo/title, product dropdown, then `木木`. This is non-secret UI
    state and works for arbitrary nicknames rather than a hard-coded account.
    """
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for line in lines[:12]:
        if _looks_like_zhuque_account_name(line):
            return line
    return ""


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
    package_dir = here.parents[3]
    candidates = [
        package_dir / "data" / "zhuque" / "creds_latest.json",
        Path.cwd() / "data" / "zhuque" / "creds_latest.json",
        Path.cwd() / "package" / "data" / "zhuque" / "creds_latest.json",
        Path.cwd().parent / "data" / "zhuque" / "creds_latest.json",
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

    labels = data.get("segment_labels")
    if isinstance(labels, list) and len(labels) > 0:
        return data

    return None


def _zhuque_payload_has_segment_labels(payload: Any) -> bool:
    data = payload if isinstance(payload, dict) else None
    labels = data.get("segment_labels") if data else None
    return isinstance(labels, list) and len(labels) > 0


def _zhuque_payload_has_score_or_ratio(payload: Any) -> bool:
    data = payload if isinstance(payload, dict) else None
    if not data:
        return False
    if data.get("confidence") is not None or data.get("rate") is not None or data.get("ai_generated") is not None:
        return True
    labels_ratio = data.get("labels_ratio") or data.get("labelsRatio")
    return isinstance(labels_ratio, dict) and bool(labels_ratio)


def _infer_raw_labels_ratio_from_segment_labels(segment_labels: Any, text_length: int) -> dict:
    """Conservative fallback when Zhuque exposes labels before/without a total score.

    Live Zhuque can render highlighted spans while the old summary payload is
    delayed or absent after a Tencent CAPTCHA challenge. Treat labelled AI /
    suspicious spans as covered risk and count unlabelled text as human, so the
    pipeline can still continue from the same solved page instead of failing on
    ``缺少有效检测分数``.
    """
    if not isinstance(segment_labels, list) or text_length <= 0:
        return {}

    lengths = {"0": 0, "1": 0, "2": 0}
    for item in segment_labels:
        if not isinstance(item, dict):
            continue
        try:
            label = int(item.get("label"))
        except (TypeError, ValueError):
            continue
        if label not in {0, 1, 2}:
            continue

        span_length = 0
        position = item.get("position")
        if (
            isinstance(position, list)
            and len(position) == 2
            and all(isinstance(value, (int, float)) for value in position)
        ):
            start = max(0, int(position[0]))
            length = int(position[1])
            if length > 0 and start < text_length:
                span_length = min(length, text_length - start)
        if span_length <= 0:
            label_text = item.get("text")
            if isinstance(label_text, str) and label_text:
                span_length = min(len(label_text), text_length)
        if span_length <= 0:
            continue
        lengths[str(label)] += span_length

    labelled_length = sum(lengths.values())
    if labelled_length <= 0:
        return {}

    ratios = {label: max(0.0, length / text_length) for label, length in lengths.items()}
    ratio_total = sum(ratios.values())
    if ratio_total > 1.0:
        ratios = {label: value / ratio_total for label, value in ratios.items()}
    else:
        # Zhuque usually returns only highlighted suspicious/AI spans. Missing
        # coverage is therefore the safest human/default bucket.
        ratios["1"] = min(1.0, ratios["1"] + (1.0 - ratio_total))
    return ratios


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _zhuque_visible_captcha_wait_seconds() -> float:
    """Extra wait budget for human-solved CAPTCHA in a visible detect window."""
    return max(0.0, _env_float("ZHUQUE_VISIBLE_CAPTCHA_WAIT_SECONDS", 600.0))


def _zhuque_detect_failure_retryable(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "超时",
            "timeout",
            "reset",
            "closed",
            "断连",
            "按钮被禁用",
            "button disabled",
            "重开页面",
        )
    )


def _zhuque_detect_headless() -> bool:
    """Whether real-page Zhuque detection should run in a hidden browser.

    Default stays headless for server deployments. Local troubleshooting can set
    ``ZHUQUE_DETECT_HEADLESS=false`` so Tencent CAPTCHA challenges appear in a
    real browser window and can be solved without abandoning the active detect
    page/context.
    """
    return _env_bool("ZHUQUE_DETECT_HEADLESS", True)


def _zhuque_detect_persistent_profile() -> bool:
    """Use a stable Chrome user-data-dir for repeated Zhuque detections."""
    return _env_bool("ZHUQUE_DETECT_PERSISTENT_PROFILE", False)


def _zhuque_detect_cdp_endpoint() -> str:
    """Optional Chrome DevTools endpoint for using a user-launched browser."""
    return os.environ.get("ZHUQUE_DETECT_CDP_ENDPOINT", "").strip().rstrip("/")


def _zhuque_page_captcha_detected(page_state: dict) -> bool:
    if not isinstance(page_state, dict):
        return False
    if page_state.get("captcha_visible") is True:
        return True
    captcha_items = page_state.get("captcha")
    if isinstance(captcha_items, list) and captcha_items:
        return True
    captcha_text = " ".join(
        str(page_state.get(key) or "")
        for key in ("captcha_text", "captcha_iframe_src", "alert", "alert_title", "button_text")
    ).lower()
    return any(
        marker in captcha_text
        for marker in (
            "tcaptcha",
            "captcha.gtimg.com",
            "verification code",
            "choose all similar",
            "refreshing too often",
            "验证码",
        )
    )


def _select_zhuque_terminal_payload(observed_payloads: list[dict]) -> Optional[dict]:
    """Pick a real terminal result, not transient empty segment arrays.

    Prefer the latest payload containing a score/ratio and merge the latest
    segment labels into it. Vue component scans can surface segment labels a
    little earlier than the summary score, especially after manual CAPTCHA; if
    labels are selected first, downstream normalization fails with a false
    ``缺少有效检测分数`` even when a scored payload was also observed.
    """
    scored_payload = next(
        (item for item in reversed(observed_payloads) if _zhuque_payload_has_score_or_ratio(item)),
        None,
    )
    label_payload = next(
        (item for item in reversed(observed_payloads) if _zhuque_payload_has_segment_labels(item)),
        None,
    )
    if isinstance(scored_payload, dict):
        payload = dict(scored_payload)
        if label_payload and not _zhuque_payload_has_segment_labels(payload):
            payload["segment_labels"] = label_payload.get("segment_labels")
        if label_payload:
            for key in ("content_type", "feedback_token"):
                if payload.get(key) is None and label_payload.get(key) is not None:
                    payload[key] = label_payload.get(key)
        return payload
    return dict(label_payload) if isinstance(label_payload, dict) else None


def _normalize_zhuque_observed_page_result(
    *,
    observed_payloads: list[dict],
    page_state: dict,
    text_length: int,
) -> Optional[dict]:
    """Normalize a real result captured from the page without requiring DOM/Vue state.

    The Zhuque page sometimes receives the terminal result in WebSocket or
    `/user/detect/result` traffic but does not expose the old
    `.ai-detection-result.__vue__.type/rate` shape. Waiting for that brittle DOM
    condition causes false timeouts after Zhuque has already consumed a detect
    quota. Traffic payloads are authoritative, so return them immediately.
    """
    payload = _select_zhuque_terminal_payload(observed_payloads)
    if payload is None:
        return None

    button_text = page_state.get("button_text") or ""
    if button_text and not any(key in payload for key in ("availableUses", "remaining_uses", "remainingUses", "button_text")):
        payload["button_text"] = button_text
    if page_state.get("alert") and not payload.get("alert_text"):
        payload["alert_text"] = str(page_state.get("alert") or "").replace("Report", "").replace("下载报告", "").strip()
    if page_state.get("alert_title") and not payload.get("alert_title"):
        payload["alert_title"] = page_state.get("alert_title")

    if _zhuque_page_captcha_detected(page_state) and not _zhuque_payload_has_score_or_ratio(payload):
        # CAPTCHA is still active; segment-label-only Vue state can be stale or
        # partial. Keep waiting for the user-solved page to emit a scored result.
        return None

    result = normalize_zhuque_result(payload, text_length=text_length, source="page_fallback")
    if not result.get("success") and not _zhuque_payload_has_score_or_ratio(payload):
        # Non-empty labels without a score are useful only if normalization can
        # infer a conservative risk. Otherwise keep polling instead of surfacing
        # a misleading terminal failure while the page may still be rendering.
        return None
    result["page_result_payload_count"] = len(observed_payloads)
    result["page_result_has_segment_labels"] = any(
        _zhuque_payload_has_segment_labels(item) for item in observed_payloads
    )
    return result


def _merge_zhuque_page_payload(*, observed_payloads: list[dict], vue: dict, page_state: dict) -> dict:
    payload = _select_zhuque_terminal_payload(observed_payloads) or {}
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
    score_inferred_from_segment_labels = False
    if not labels_ratio:
        inferred_raw_labels = _infer_raw_labels_ratio_from_segment_labels(
            data.get("segment_labels"),
            text_length,
        )
        if inferred_raw_labels:
            labels_ratio, label_map = _infer_and_convert_labels(inferred_raw_labels, raw_rate)
            score_inferred_from_segment_labels = True
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

    result = {
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
    if score_inferred_from_segment_labels:
        result["score_inferred_from_segment_labels"] = True
    return result


class ZhuqueAPI:
    """微信扫码凭证 + 朱雀真实页面检测客户端。"""

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
        # Real-page detection is now the primary detect path because Zhuque's
        # CAPTCHA WebSocket shortcut can return code=21/diff. Keep one browser
        # alive per service instance so repeated detects look like one returning
        # visitor instead of many fresh automated sessions.
        self._pw = None
        self._browser = None
        self._browser_context = None
        self._browser_context_anonymous: Optional[bool] = None
        self._browser_context_needs_refresh = False
        self._browser_persistent_profile = False
        self._browser_profile_dir: Optional[Path] = None
        self._browser_external_context = False
        self._browser_cdp_endpoint: Optional[str] = None
        self._browser_cdp_managed = False
        self._browser_cdp_process = None
        self._preferred_cdp_endpoint_managed = False
        self._cached_page = None
        self._ws_handler_ref = None
        self._response_handler_ref = None
        self._last_detect_time = 0.0
        self._last_detect_failed = False
        self._detect_cooldown = 8.0
        self._detect_cooldown_after_fail = 30.0
        self._browser_headless = True

    def _playwright_browsers_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / ".playwright-browsers"

    def _detect_profile_dir(self, *, anonymous: bool) -> Path:
        profile_name = "detect_chrome_profile_anonymous" if anonymous else "detect_chrome_profile"
        return self.credentials_file.parent / profile_name

    def _detect_system_browser_profile_dir(self, executable: str) -> str:
        configured = os.environ.get("ZHUQUE_DETECT_BROWSER_USER_DATA_DIR", "").strip()
        if configured:
            return configured
        if self._is_windows_browser_executable(executable):
            local_app_data = self._windows_local_app_data()
            return local_app_data.rstrip("\\/") + r"\GankAIGC\ZhuqueDetectBrowserProfile"
        return str(self.credentials_file.parent / "detect_system_browser_profile")

    @staticmethod
    def _is_wsl() -> bool:
        if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
            return True
        try:
            release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
        except OSError:
            return False
        return "microsoft" in release or "wsl" in release

    @staticmethod
    def _run_text(args: list[str], timeout: float = 3.0) -> str:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (completed.stdout or "").strip()

    @classmethod
    def _windows_to_wsl_path(cls, path: str) -> Optional[Path]:
        text = (path or "").strip().strip('"')
        if not text:
            return None
        converted = cls._run_text(["wslpath", "-u", text], timeout=2.0) if cls._is_wsl() else ""
        if converted:
            return Path(converted)
        match = re.match(r"^([a-zA-Z]):\\(.*)$", text)
        if match:
            drive, rest = match.groups()
            linux_rest = rest.replace("\\", "/")
            return Path(f"/mnt/{drive.lower()}/{linux_rest}")
        return None

    @classmethod
    def _windows_local_app_data(cls) -> str:
        configured = os.environ.get("ZHUQUE_WINDOWS_CHROME_USER_DATA_DIR", "").strip()
        if configured:
            return configured
        local_app_data_env = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data_env:
            return local_app_data_env
        local_app_data = cls._run_text(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "[Environment]::GetFolderPath('LocalApplicationData')",
            ],
            timeout=3.0,
        )
        if local_app_data:
            return local_app_data
        return r"C:\GankAIGC"

    @staticmethod
    def _is_windows_browser_executable(executable: str | None) -> bool:
        if not executable:
            return False
        text = str(executable).lower()
        return text.endswith(".exe") or text.startswith("/mnt/")

    def _find_detect_browser_executable(self) -> Optional[str]:
        env_path = os.environ.get("ZHUQUE_DETECT_BROWSER_EXECUTABLE") or os.environ.get("ZHUQUE_CHROME_EXECUTABLE")
        windows_env_path = self._windows_to_wsl_path(env_path) if self._is_wsl() and env_path else None
        candidates: list[Any] = [env_path, windows_env_path]
        if os.name == "nt":
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            candidates.extend(
                [
                    rf"{program_files}\Google\Chrome\Application\chrome.exe",
                    rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
                    rf"{program_files}\Microsoft\Edge\Application\msedge.exe",
                    rf"{program_files_x86}\Microsoft\Edge\Application\msedge.exe",
                    rf"{program_files}\BraveSoftware\Brave-Browser\Application\brave.exe",
                    rf"{program_files_x86}\BraveSoftware\Brave-Browser\Application\brave.exe",
                    rf"{local_app_data}\Google\Chrome\Application\chrome.exe" if local_app_data else None,
                ]
            )
        if self._is_wsl():
            candidates.extend(
                [
                    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
                    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
                    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
                    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                    "/mnt/c/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
                    "/mnt/c/Program Files (x86)/BraveSoftware/Brave-Browser/Application/brave.exe",
                ]
            )
        candidates.extend(
            [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/msedge",
                "/usr/bin/brave-browser",
                "/usr/bin/brave",
                "/snap/bin/chromium",
                "/snap/bin/brave",
            ]
        )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(candidate)
        return None

    def _detect_cdp_port(self) -> int:
        try:
            return int(os.environ.get("ZHUQUE_DETECT_CDP_PORT") or "9224")
        except (TypeError, ValueError):
            return 9224

    @staticmethod
    def _urlopen_no_proxy(url: str, timeout: float):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(url, timeout=timeout)

    def _cdp_endpoints(self, port: int) -> list[str]:
        hosts = ["127.0.0.1", "localhost"]
        if self._is_wsl():
            try:
                resolv_conf = Path("/etc/resolv.conf").read_text(encoding="utf-8")
            except OSError:
                resolv_conf = ""
            match = re.search(r"^nameserver\s+([0-9.]+)", resolv_conf, flags=re.MULTILINE)
            if match and match.group(1) not in hosts:
                hosts.append(match.group(1))
        return [f"http://{host}:{port}" for host in hosts]

    def _wait_for_cdp(self, port: int, timeout: float = 8.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for endpoint in self._cdp_endpoints(port):
                try:
                    with self._urlopen_no_proxy(f"{endpoint}/json/version", timeout=0.5) as response:
                        if response.status == 200:
                            return endpoint
                except (OSError, urllib.error.URLError):
                    continue
            time.sleep(0.25)
        return ""

    def _ensure_system_browser_cdp_endpoint(self) -> str:
        port = self._detect_cdp_port()
        existing = self._wait_for_cdp(port, timeout=0.5)
        if existing:
            return existing
        executable = self._find_detect_browser_executable()
        if not executable:
            return ""
        profile_dir = self._detect_system_browser_profile_dir(executable)
        if not self._is_windows_browser_executable(executable):
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
        args = [
            executable,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            f"--app={self.http_base_url}/ai-detect/",
            "--window-size=1280,800",
            "--window-position=120,80",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
        ]
        if self._is_wsl() and self._is_windows_browser_executable(executable):
            args.insert(2, "--remote-debugging-address=0.0.0.0")
        try:
            self._browser_cdp_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            return ""
        return self._wait_for_cdp(port, timeout=10.0)

    def _preferred_detect_cdp_endpoint(self) -> str:
        self._preferred_cdp_endpoint_managed = False
        configured = _zhuque_detect_cdp_endpoint()
        if configured:
            return configured
        if _zhuque_detect_headless() or not _env_bool("ZHUQUE_DETECT_AUTO_SYSTEM_BROWSER", True):
            return ""
        endpoint = self._ensure_system_browser_cdp_endpoint()
        self._preferred_cdp_endpoint_managed = bool(endpoint)
        return endpoint

    async def focus_cached_page(self) -> dict:
        """Bring the existing visible Zhuque detect page forward when possible.

        Manual Tencent CAPTCHA resolution should reuse the real-page detector's
        current tab instead of launching a second local-window sync browser. The
        method never creates a new page; it only focuses an already-live page in
        this service instance.
        """
        candidates = []
        if self._cached_page is not None:
            candidates.append(self._cached_page)
        if self._browser_context is not None:
            with contextlib.suppress(Exception):
                candidates.extend(getattr(self._browser_context, "pages", []) or [])

        seen: set[int] = set()
        live_pages = []
        for candidate in candidates:
            if candidate is None or id(candidate) in seen:
                continue
            seen.add(id(candidate))
            try:
                if candidate.is_closed():
                    continue
            except Exception:
                continue
            live_pages.append(candidate)

        if not live_pages:
            return {
                "available": False,
                "headless": self._browser_headless,
                "credential_file": str(self.credentials_file),
                "message": "当前没有可复用的朱雀检测窗口",
            }

        page = next(
            (candidate for candidate in live_pages if "matrix.tencent.com/ai-detect" in str(getattr(candidate, "url", ""))),
            live_pages[0],
        )
        if self._browser_headless:
            return {
                "available": False,
                "headless": True,
                "credential_file": str(self.credentials_file),
                "url": str(getattr(page, "url", "")),
                "message": "当前朱雀检测浏览器是无头模式，无法前置可见窗口",
            }

        try:
            await page.bring_to_front()
        except Exception as exc:
            return {
                "available": False,
                "headless": self._browser_headless,
                "credential_file": str(self.credentials_file),
                "url": str(getattr(page, "url", "")),
                "message": f"复用朱雀检测窗口失败: {exc}",
            }
        self._cached_page = page
        return {
            "available": True,
            "headless": False,
            "credential_file": str(self.credentials_file),
            "url": str(getattr(page, "url", "")),
            "message": "已复用当前朱雀检测窗口",
        }

    async def open_detect_page(self) -> dict:
        """Open or focus a visible Zhuque detection page without submitting text.

        This is the built-in local/one-click launcher. It avoids spawning the
        legacy ``package/backend/app/tools/zhuque_capture_window.py`` helper,
        which is not available as a normal Python script inside PyInstaller one-click builds.
        """
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {
                "available": False,
                "status": "manual_required",
                "headless": self._browser_headless,
                "credential_file": str(self.credentials_file),
                "message": f"当前环境未安装 Playwright，无法打开本机朱雀页面: {exc}",
            }

        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self._playwright_browsers_path()))
        status = self.credential_status()
        anonymous = not bool(status.get("has_token"))
        try:
            cdp_endpoint = self._preferred_detect_cdp_endpoint()
            if cdp_endpoint:
                await self._ensure_cdp_context(async_playwright, anonymous=anonymous, endpoint=cdp_endpoint)
            elif _zhuque_detect_persistent_profile():
                await self._ensure_persistent_profile_context(async_playwright, anonymous=anonymous)
            else:
                browser = await self._launch_persistent_browser(async_playwright)
                if self._browser_context is None:
                    self._browser_context = await browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent=DEFAULT_USER_AGENT,
                    )
                    self._browser_context_anonymous = anonymous

            page = None
            if self._cached_page is not None:
                with contextlib.suppress(Exception):
                    if not self._cached_page.is_closed():
                        page = self._cached_page
            if page is None and self._browser_context is not None:
                with contextlib.suppress(Exception):
                    live_pages = [candidate for candidate in (getattr(self._browser_context, "pages", []) or []) if not candidate.is_closed()]
                    page = next(
                        (candidate for candidate in live_pages if "matrix.tencent.com/ai-detect" in str(getattr(candidate, "url", ""))),
                        live_pages[0] if live_pages else None,
                    )
            page_already_on_zhuque = bool(page and "matrix.tencent.com/ai-detect" in str(getattr(page, "url", "")))
            if page is None:
                page = await self._browser_context.new_page()
                page_already_on_zhuque = False

            if not anonymous and (not self._browser_external_context or self._browser_cdp_managed):
                try:
                    creds = self.load_credentials(refresh=False) or {}
                except Exception:
                    creds = {}
                local_storage = self._page_local_storage_from_credentials(creds)
                if local_storage:
                    local_storage_json = json.dumps(local_storage, ensure_ascii=False)
                    await page.add_init_script(
                        f"""
                        (() => {{
                            const data = {local_storage_json};
                            for (const [k, v] of Object.entries(data)) {{
                                try {{ localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); }} catch (e) {{}}
                            }}
                        }})();
                        """
                    )
                    with contextlib.suppress(Exception):
                        await page.evaluate(
                            """(data) => {
                                for (const [k, v] of Object.entries(data || {})) {
                                    try { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); } catch (e) {}
                                }
                            }""",
                            local_storage,
                        )

            if not page_already_on_zhuque:
                await page.goto(f"{self.http_base_url}/ai-detect/", wait_until="domcontentloaded", timeout=60000)
            with contextlib.suppress(Exception):
                await page.bring_to_front()
            self._cached_page = page
            return {
                "available": True,
                "status": "opened",
                "headless": self._browser_headless,
                "credential_file": str(self.credentials_file),
                "url": str(getattr(page, "url", "")),
                "message": "已打开本机朱雀页面，请在该窗口完成登录/验证码后回到 GankAIGC 同步状态",
            }
        except Exception as exc:
            logger.warning("打开本机朱雀页面失败: %s", exc, exc_info=True)
            return {
                "available": False,
                "status": "manual_required",
                "headless": self._browser_headless,
                "credential_file": str(self.credentials_file),
                "message": f"打开本机朱雀页面失败: {exc}",
            }

    async def _seed_persistent_context_state(self, context, *, anonymous: bool) -> None:
        """Seed a fixed browser profile from the latest per-user Zhuque state.

        ``launch_persistent_context`` cannot take Playwright's ``storage_state``
        option directly, so import cookies and localStorage after the profile is
        opened. The profile then keeps future Zhuque-issued device state on disk.
        """
        if anonymous:
            state = self._anonymous_page_storage_state() or {}
        else:
            state_file = self.credentials_file.parent / "browser_state.json"
            try:
                state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
            except (OSError, json.JSONDecodeError):
                state = {}
        cookies = state.get("cookies") if isinstance(state, dict) else None
        if isinstance(cookies, list) and cookies:
            with contextlib.suppress(Exception):
                await context.add_cookies(cookies)
        origins = state.get("origins") if isinstance(state, dict) else None
        if isinstance(origins, list) and origins:
            local_storage_by_origin = {
                str(origin.get("origin")): {
                    str(item.get("name")): item.get("value")
                    for item in (origin.get("localStorage") or [])
                    if isinstance(item, dict) and item.get("name") is not None and item.get("value") is not None
                }
                for origin in origins
                if isinstance(origin, dict) and origin.get("origin")
            }
            local_storage_json = json.dumps(local_storage_by_origin, ensure_ascii=False)
            await context.add_init_script(
                f"""
                (() => {{
                    const states = {local_storage_json};
                    const data = states[location.origin] || {{}};
                    for (const [k, v] of Object.entries(data)) {{
                        try {{ localStorage.setItem(k, String(v)); }} catch (e) {{}}
                    }}
                }})();
                """
            )

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
                "请先点击“打开朱雀页面”或运行 package/backend/app/tools/zhuque_capture_window.py"
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
        """Forget cached auth and refresh the persistent page context on next detect."""
        self._credentials_cache = None
        self._browser_context_needs_refresh = True

    def _page_local_storage_from_credentials(self, creds: dict) -> dict:
        """Return captured Zhuque localStorage for page fallback injection.

        ``load_credentials()`` normalizes token/fp fields and keeps the original
        credential JSON under ``raw``. The real Zhuque page expects the original
        localStorage keys (not only the normalized ``access_token`` field), so
        page fallback must inject those keys before navigation.
        """
        raw = creds.get("raw") if isinstance(creds, dict) else {}
        local_storage = (raw.get("localStorage") or raw.get("local_storage")) if isinstance(raw, dict) else {}
        storage = dict(local_storage) if isinstance(local_storage, dict) else {}
        access_token = str(creds.get("access_token") or "") if isinstance(creds, dict) else ""
        fp = str(creds.get("fp") or "") if isinstance(creds, dict) else ""
        if access_token and not _unwrap_token_value(storage.get("aiGenAccessToken")):
            storage["aiGenAccessToken"] = access_token
        if fp and not storage.get("fp"):
            storage["fp"] = fp
        return {str(key): value for key, value in storage.items() if key is not None and value is not None}

    async def _close_persistent_page_context(self) -> None:
        external_context = self._browser_external_context
        if self._cached_page is not None and not external_context:
            with contextlib.suppress(Exception):
                await self._cached_page.close()
        self._cached_page = None
        self._ws_handler_ref = None
        self._response_handler_ref = None
        if self._browser_context is not None and not external_context:
            with contextlib.suppress(Exception):
                await self._browser_context.close()
        if self._browser_persistent_profile or external_context:
            self._browser = None
        self._browser_context = None
        self._browser_context_anonymous = None
        self._browser_context_needs_refresh = False
        self._browser_persistent_profile = False
        self._browser_profile_dir = None
        self._browser_external_context = False
        self._browser_cdp_endpoint = None
        self._browser_cdp_managed = False

    async def close(self) -> None:
        """Close the persistent Playwright resources used by real-page detect."""
        external_context = self._browser_external_context
        await self._close_persistent_page_context()
        if self._browser is not None and not external_context:
            with contextlib.suppress(Exception):
                await self._browser.close()
        self._browser = None
        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()
        self._pw = None

    async def _launch_persistent_browser(self, async_playwright_factory):
        if self._pw is None:
            self._pw = await async_playwright_factory().start()
        if self._browser is not None:
            if self._browser_external_context:
                await self._close_persistent_page_context()
                self._browser = None
            else:
                with contextlib.suppress(Exception):
                    if self._browser.is_connected():
                        return self._browser
                await self._close_persistent_page_context()
                self._browser = None

        desired_headless = _zhuque_detect_headless()
        launch_kwargs = {
            "headless": desired_headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        try:
            self._browser = await self._pw.chromium.launch(channel="chrome", **launch_kwargs)
            self._browser_headless = desired_headless
        except Exception as exc:
            logger.info(
                "朱雀真实页面检测未能启动 Chrome channel，回退 Playwright Chromium: %s",
                exc,
            )
            try:
                self._browser = await self._pw.chromium.launch(**launch_kwargs)
                self._browser_headless = desired_headless
            except Exception:
                if desired_headless:
                    raise
                logger.exception("朱雀真实页面检测可见浏览器启动失败，回退无头模式")
                fallback_kwargs = dict(launch_kwargs)
                fallback_kwargs["headless"] = True
                self._browser = await self._pw.chromium.launch(**fallback_kwargs)
                self._browser_headless = True
        return self._browser

    async def _ensure_cdp_context(self, async_playwright_factory, *, anonymous: bool, endpoint: str = ""):
        endpoint = (endpoint or self._preferred_detect_cdp_endpoint()).strip().rstrip("/")
        if not endpoint:
            raise RuntimeError("朱雀检测未找到可用的本机浏览器调试端点")
        if self._pw is None:
            self._pw = await async_playwright_factory().start()
        if (
            self._browser_context is not None
            and self._browser_external_context
            and self._browser_cdp_endpoint == endpoint
            and self._browser_context_anonymous == anonymous
            and not self._browser_context_needs_refresh
        ):
            return self._browser_context

        managed_endpoint = bool(self._preferred_cdp_endpoint_managed)
        previous_browser = self._browser
        previous_external = self._browser_external_context
        await self._close_persistent_page_context()
        if previous_browser is not None and not previous_external:
            with contextlib.suppress(Exception):
                await previous_browser.close()
        self._browser = await self._pw.chromium.connect_over_cdp(endpoint)
        contexts = getattr(self._browser, "contexts", []) or []
        self._browser_context = contexts[0] if contexts else await self._browser.new_context()
        self._browser_context_anonymous = anonymous
        self._browser_context_needs_refresh = False
        self._browser_persistent_profile = False
        self._browser_profile_dir = None
        self._browser_external_context = True
        self._browser_cdp_endpoint = endpoint
        self._browser_cdp_managed = managed_endpoint
        self._browser_headless = False
        return self._browser_context

    async def _ensure_persistent_profile_context(self, async_playwright_factory, *, anonymous: bool):
        if self._pw is None:
            self._pw = await async_playwright_factory().start()

        desired_headless = _zhuque_detect_headless()
        profile_dir = self._detect_profile_dir(anonymous=anonymous)
        if (
            self._browser_context is not None
            and self._browser_persistent_profile
            and self._browser_profile_dir == profile_dir
            and self._browser_context_anonymous == anonymous
            and not self._browser_context_needs_refresh
        ):
            return self._browser_context

        previous_browser = self._browser
        previous_external = self._browser_external_context
        await self._close_persistent_page_context()
        if previous_browser is not None and not previous_external:
            with contextlib.suppress(Exception):
                await previous_browser.close()
        self._browser = None

        profile_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs = {
            "headless": desired_headless,
            "viewport": {"width": 1280, "height": 720},
            "user_agent": DEFAULT_USER_AGENT,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        try:
            self._browser_context = await self._pw.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                **launch_kwargs,
            )
            self._browser_headless = desired_headless
        except Exception as exc:
            logger.info(
                "朱雀真实页面检测未能用固定 profile 启动 Chrome channel，回退 Playwright Chromium: %s",
                exc,
            )
            try:
                self._browser_context = await self._pw.chromium.launch_persistent_context(
                    str(profile_dir),
                    **launch_kwargs,
                )
                self._browser_headless = desired_headless
            except Exception:
                if desired_headless:
                    raise
                logger.exception("朱雀真实页面检测固定 profile 可见浏览器启动失败，回退无头模式")
                fallback_kwargs = dict(launch_kwargs)
                fallback_kwargs["headless"] = True
                self._browser_context = await self._pw.chromium.launch_persistent_context(
                    str(profile_dir),
                    **fallback_kwargs,
                )
                self._browser_headless = True
        await self._seed_persistent_context_state(self._browser_context, anonymous=anonymous)
        self._browser_context_anonymous = anonymous
        self._browser_context_needs_refresh = False
        self._browser_persistent_profile = True
        self._browser_profile_dir = profile_dir
        self._browser = getattr(self._browser_context, "browser", None)
        return self._browser_context

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
        last_state: dict = {}
        try:
            open_result = await self.open_detect_page()
            if not open_result.get("available"):
                return {
                    "remaining_uses": -1,
                    "button_enabled": False,
                    "page_found": False,
                    "quota_text": "",
                    "message": open_result.get("message") or "无法打开本机朱雀页面探测剩余次数",
                }
            page = self._cached_page
            if page is None:
                return {
                    "remaining_uses": -1,
                    "button_enabled": False,
                    "page_found": False,
                    "quota_text": "",
                    "message": "本机朱雀页面未就绪，请重新点击打开朱雀页面",
                }
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
                        let accessToken = '';
                        const readLocalStorage = (key) => {
                            try { return (localStorage.getItem(key) || '').trim(); } catch (_) { return ''; }
                        };
                        try {
                            anonymousFp = readLocalStorage('fp');
                            const tokenKeys = ['aiGenAccessToken', 'access_token', 'accessToken', 'token', 'authToken'];
                            for (const key of tokenKeys) {
                                const raw = readLocalStorage(key);
                                if (!raw) continue;
                                try {
                                    const parsed = JSON.parse(raw);
                                    accessToken = String(parsed.value || parsed.token || parsed.access_token || raw || '').trim();
                                } catch (_) {
                                    accessToken = raw;
                                }
                                if (accessToken) break;
                            }
                        } catch (_) {
                            anonymousFp = '';
                            accessToken = '';
                        }
                        const ignoredAccountTexts = /Zhuque AI Detection Assistant|AI Detection Assistant|Free AI Detection Assistant|Text|Image\/Video|Upload|Clear|Detect|Detecting|Important Notice|Invited tester|Notice|Abilities|Model update|登录|login|Upload|Report/i;
                        const normalizeAccountText = (text) => (text || '').replace(/\s+/g, ' ').trim();
                        const looksLikeAccountName = (text) => (
                            text
                            && text.length <= 24
                            && !ignoredAccountTexts.test(text)
                            && !maybeQuotaText(text)
                            && !/^[-_•|/\\]+$/.test(text)
                        );
                        const headerAccountCandidates = [...document.querySelectorAll('header *, .header *, [class*="header"] *, [class*="user"] *, [class*="avatar"] *, [class*="account"] *, [class*="dropdown"] *, .el-dropdown *, .el-dropdown-link')]
                            .map((el) => normalizeAccountText(el.textContent))
                            .filter(looksLikeAccountName);
                        const visibleTopTextCandidates = [...document.querySelectorAll('body *')]
                            .map((el) => {
                                const text = normalizeAccountText(el.textContent);
                                const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : { top: 9999, right: 0, width: 0, height: 0 };
                                const visible = !!(el.offsetWidth || el.offsetHeight || (el.getClientRects && el.getClientRects().length));
                                return { text, top: rect.top || 9999, right: rect.right || 0, visible };
                            })
                            .filter((item) => item.visible && item.top >= 0 && item.top <= 180 && looksLikeAccountName(item.text))
                            .sort((a, b) => (b.right - a.right) || (a.top - b.top))
                            .map((item) => item.text);
                        const accountName = headerAccountCandidates[0] || visibleTopTextCandidates[0] || '';
                        return {
                            quota_texts: candidates.slice(0, 48).map((item) => item.value),
                            quota_sources: candidates.slice(0, 48),
                            vue_signals: vueSignals.slice(0, 48),
                            fp: anonymousFp,
                            anonymous_fp: anonymousFp,
                            access_token_present: Boolean(accessToken),
                            has_token: Boolean(accessToken),
                            logged_in: Boolean(accessToken || accountName),
                            user_name: accountName,
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

            def page_identity(state: dict) -> tuple[bool, str]:
                body_user_name = _extract_account_name_from_body_preview(state.get("body_preview") or "")
                page_user_name = body_user_name or str(state.get("user_name") or "").strip()
                page_has_login = bool(state.get("has_token") or state.get("access_token_present") or state.get("logged_in") or page_user_name)
                return page_has_login, page_user_name

            while time.time() < deadline:
                last_state = await collect_quota_state()
                page_has_login, page_user_name = page_identity(last_state)
                remaining_uses = _coerce_remaining_uses(*(last_state.get("quota_texts") or []))
                if remaining_uses >= 0:
                    return {
                        "remaining_uses": remaining_uses,
                        "button_enabled": remaining_uses > 0,
                        "page_found": bool(last_state.get("page_found")),
                        "quota_text": " | ".join(last_state.get("quota_texts") or []),
                        "fp": str(last_state.get("fp") or "").strip(),
                        "anonymous_fp": str(last_state.get("anonymous_fp") or last_state.get("fp") or "").strip(),
                        "has_token": page_has_login,
                        "user_name": page_user_name,
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
                        "has_token": page_has_login,
                        "user_name": page_user_name,
                        "has_anonymous_fp": bool(last_state.get("has_anonymous_fp") or last_state.get("anonymous_fp") or last_state.get("fp")),
                        "probe_state": last_state,
                        "message": "朱雀页面检测入口可用，但当前页面未暴露剩余次数数字",
                    }
                await page.wait_for_timeout(500)

            page_has_login, page_user_name = page_identity(last_state)
            await self._write_quota_probe_artifacts(page, reason="quota_not_found", quota_state=last_state)
            return {
                "remaining_uses": -1,
                "button_enabled": bool(last_state.get("button_enabled")),
                "page_found": bool(last_state.get("page_found")),
                "quota_text": last_state.get("submit_button_text") or "",
                "fp": str(last_state.get("fp") or "").strip(),
                "anonymous_fp": str(last_state.get("anonymous_fp") or last_state.get("fp") or "").strip(),
                "has_token": page_has_login,
                "user_name": page_user_name,
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

    async def _peek_remaining_uses_with_page(self, timeout: float = 5.0) -> Optional[int]:
        """Compatibility wrapper returning only a known numeric anonymous quota."""
        status = await self._peek_quota_status_with_page(timeout=timeout)
        remaining_uses = _coerce_remaining_uses(status.get("remaining_uses"), status.get("quota_text"))
        return remaining_uses if remaining_uses >= 0 else None

    async def peek_quota_status(self, timeout: float = 3.0, *, allow_anonymous: bool = False) -> dict:
        """Return live quota state, preserving button availability when count is hidden.

        In local/one-click visible-browser mode, the open Zhuque page is the
        source of truth. A cached anonymous fp can legitimately report the free
        quota even while the visible page is logged into a real account, so page
        probing must run before the anonymous WebSocket fp fallback.
        """
        creds = None
        if allow_anonymous:
            page_status = await self._peek_quota_status_with_page(timeout=timeout)
            page_remaining = _coerce_remaining_uses(page_status.get("remaining_uses"), page_status.get("quota_text"))
            if page_status.get("has_token") or page_remaining >= 0 or page_status.get("button_enabled"):
                return page_status
            try:
                creds = self.load_credentials(refresh=True)
            except RuntimeError:
                return page_status
            if not creds.get("access_token") and not creds.get("fp"):
                return page_status
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

    @staticmethod
    def _bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple, p3: tuple) -> tuple[float, float]:
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        return x, y

    async def _human_mouse_move(
        self,
        page,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int = 600,
    ) -> None:
        """Move with a cubic Bezier path instead of a one-shot bot-like jump."""
        cp1 = (x1 + (x2 - x1) * 0.25 + random.randint(-60, 60), y1 + random.randint(-40, 40))
        cp2 = (x2 - (x2 - x1) * 0.25 + random.randint(-50, 50), y2 + random.randint(-30, 30))
        steps = max(12, duration_ms // 20)
        for i in range(steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            x, y = self._bezier_point(eased, (x1, y1), cp1, cp2, (x2, y2))
            await page.mouse.move(x, y)
            await page.wait_for_timeout(max(1, duration_ms // steps))

    async def _detect_with_page(self, text: str, timeout: float, *, reason: str = "", anonymous: bool = False) -> dict:
        """Run detection through the real Zhuque page.

        The direct WebSocket CAPTCHA shortcut is no longer trusted for text
        detection; it can return ``code=21``/``diff`` before the text is even
        submitted. This path lets Zhuque's own page obtain valid CAPTCHA state,
        while preserving the traffic-result capture already used by GankAIGC.
        """
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return self._failure(
                f"朱雀无头 API 验证失败，且当前环境未安装 Playwright，无法启用真实页面检测。{reason}",
                len(text),
            )

        since_last = time.time() - self._last_detect_time
        min_wait = self._detect_cooldown_after_fail if self._last_detect_failed else self._detect_cooldown
        if since_last < min_wait:
            await asyncio.sleep(min_wait - since_last)

        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self._playwright_browsers_path()))
        page = None
        is_cached = False
        try:
            cdp_endpoint = self._preferred_detect_cdp_endpoint()
            if cdp_endpoint:
                await self._ensure_cdp_context(async_playwright, anonymous=anonymous, endpoint=cdp_endpoint)
            elif _zhuque_detect_persistent_profile():
                await self._ensure_persistent_profile_context(async_playwright, anonymous=anonymous)
            else:
                browser = await self._launch_persistent_browser(async_playwright)
                if (
                    self._browser_context_needs_refresh
                    or self._browser_context_anonymous is not None
                    and self._browser_context_anonymous != anonymous
                ):
                    await self._close_persistent_page_context()

                if self._browser_context is None:
                    ctx_kwargs = {
                        "viewport": {"width": 1280, "height": 720},
                        "user_agent": DEFAULT_USER_AGENT,
                    }
                    state_file = self.credentials_file.parent / "browser_state.json"
                    if anonymous:
                        anonymous_storage_state = self._anonymous_page_storage_state()
                        if anonymous_storage_state:
                            ctx_kwargs["storage_state"] = anonymous_storage_state
                    elif state_file.exists():
                        ctx_kwargs["storage_state"] = str(state_file)
                    self._browser_context = await browser.new_context(**ctx_kwargs)
                    self._browser_context_anonymous = anonymous

            if self._cached_page is not None:
                with contextlib.suppress(Exception):
                    if self._cached_page.is_closed():
                        self._cached_page = None
                        self._ws_handler_ref = None
                        self._response_handler_ref = None

            if self._cached_page is not None:
                page = self._cached_page
                is_cached = True
            else:
                page = None
                if self._browser_external_context:
                    with contextlib.suppress(Exception):
                        live_pages = [candidate for candidate in (getattr(self._browser_context, "pages", []) or []) if not candidate.is_closed()]
                        page = next(
                            (candidate for candidate in live_pages if "matrix.tencent.com/ai-detect" in str(getattr(candidate, "url", ""))),
                            live_pages[0] if live_pages else None,
                        )
                if page is None:
                    page = await self._browser_context.new_page()
                is_cached = False
            self._cached_page = page
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

            if is_cached:
                if self._ws_handler_ref is not None:
                    with contextlib.suppress(Exception):
                        page.remove_listener("websocket", self._ws_handler_ref)
                if self._response_handler_ref is not None:
                    with contextlib.suppress(Exception):
                        page.remove_listener("response", self._response_handler_ref)

            def on_response_event(response) -> None:
                asyncio.create_task(on_response(response))

            page.on("websocket", on_websocket)
            page.on("response", on_response_event)
            self._ws_handler_ref = on_websocket
            self._response_handler_ref = on_response_event

            if not is_cached and not anonymous and (not self._browser_external_context or self._browser_cdp_managed):
                try:
                    creds = self.load_credentials(refresh=False) or {}
                except Exception:
                    creds = {}
                local_storage = self._page_local_storage_from_credentials(creds)
                if local_storage:
                    local_storage_json = json.dumps(local_storage, ensure_ascii=False)
                    await page.add_init_script(
                        f"""
                        (() => {{
                            const data = {local_storage_json};
                            for (const [k, v] of Object.entries(data)) {{
                                try {{
                                    localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
                                }} catch (e) {{}}
                            }}
                        }})();
                        """
                    )
                    with contextlib.suppress(Exception):
                        await page.evaluate(
                            """(data) => {
                                for (const [k, v] of Object.entries(data || {})) {
                                    try { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); } catch (e) {}
                                }
                            }""",
                            local_storage,
                        )

            if not is_cached:
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
            else:
                await page.evaluate(
                    """() => {
                        const button = document.querySelector('.clear-btn')
                            || [...document.querySelectorAll('button')].find(b => /清空|Clear/i.test(b.textContent || ''));
                        if (button) button.click();
                    }"""
                )
                await page.wait_for_timeout(300)
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
                return self._failure("朱雀真实页面检测失败：找不到文本输入框", len(text))

            await self._human_mouse_move(page, 120, 480, 380, 360, duration_ms=500)
            await page.wait_for_timeout(random.randint(80, 200))
            await self._human_mouse_move(page, 380, 360, 520, 400, duration_ms=350)
            await page.wait_for_timeout(random.randint(60, 150))
            await page.mouse.wheel(0, random.randint(60, 180))
            await page.wait_for_timeout(random.randint(100, 300))
            await page.mouse.click(540, 420, delay=random.randint(50, 100))
            await page.wait_for_timeout(random.randint(150, 400))
            await self._human_mouse_move(page, 540, 420, 650, 580, duration_ms=450)
            await page.wait_for_timeout(random.randint(80, 250))

            button_state = {}
            for _ in range(24):
                button_state = await page.evaluate(
                    """() => {
                        const button = document.querySelector('.submit-btn')
                            || [...document.querySelectorAll('button')].find(b => /立即检测|Detect/i.test(b.textContent || ''));
                        const textEl = document.querySelector('.el-textarea__inner, textarea, [contenteditable="true"]');
                        const captchaNodes = [...document.querySelectorAll(
                            '#tcaptcha_iframe_dy, #tcaptcha_wrapper_transform_dy, iframe[src*="captcha.gtimg.com"], .tcaptcha-transform, [id*=captcha], [class*=captcha]'
                        )];
                        const visibleCaptchaNodes = captchaNodes.filter((el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                        });
                        return {
                            found: Boolean(button),
                            disabled: button ? Boolean(button.disabled) : false,
                            text: button ? (button.textContent || '').trim() : '',
                            input_length: textEl ? String('value' in textEl ? textEl.value : textEl.textContent || '').length : -1,
                            captcha_visible: visibleCaptchaNodes.length > 0,
                            captcha_text: visibleCaptchaNodes
                                .map((el) => `${el.tagName || ''}#${el.id || ''}.${el.className || ''} ${el.src || ''} ${(el.textContent || '').trim()}`)
                                .join(' | ')
                                .slice(0, 500),
                        };
                    }"""
                )
                if not button_state.get("found") or not button_state.get("disabled"):
                    break
                if _zhuque_page_captcha_detected(button_state):
                    break
                await page.wait_for_timeout(500)

            if not button_state.get("found"):
                return self._failure("朱雀真实页面检测失败：找不到检测按钮", len(text))
            if button_state.get("disabled"):
                if _zhuque_page_captcha_detected(button_state):
                    return _captcha_required_zhuque_result(
                        "朱雀触发腾讯验证码，请在当前朱雀检测窗口手动完成验证后重试",
                        len(text),
                    )
                await self._write_quota_probe_artifacts(
                    page,
                    reason="detect_button_disabled_before_click",
                    quota_state={
                        "button_text": button_state.get("text") or "",
                        "input_length": button_state.get("input_length"),
                        "set_result": str(set_result),
                        "headless": self._browser_headless,
                    },
                )
                await self._close_persistent_page_context()
                return self._failure(
                    "朱雀真实页面检测临时失败：检测按钮被禁用，已重开页面重试（可能文本尚未写入或旧检测状态未清空）",
                    len(text),
                )

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
                return self._failure("朱雀真实页面检测失败：找不到检测按钮", len(text))
            if "DISABLED" in str(click_result):
                await self._close_persistent_page_context()
                return self._failure("朱雀真实页面检测临时失败：检测按钮被禁用，已重开页面重试", len(text))

            deadline = time.time() + timeout
            captcha_seen = False
            captcha_artifact_written = False
            captcha_deadline_extended = False
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
                            const hasSegments = Array.isArray(value.segment_labels) && value.segment_labels.length > 0;
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
                        const captchaNodes = [...document.querySelectorAll(
                            '#tcaptcha_iframe_dy, #tcaptcha_wrapper_transform_dy, iframe[src*="captcha.gtimg.com"], .tcaptcha-transform, [id*=captcha], [class*=captcha]'
                        )];
                        const visibleCaptchaNodes = captchaNodes.filter((el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                        });
                        const captchaText = visibleCaptchaNodes
                            .map((el) => `${el.tagName || ''}#${el.id || ''}.${el.className || ''} ${el.src || ''} ${(el.textContent || '').trim()}`)
                            .join(' | ')
                            .slice(0, 500);
                        return {
                            vue,
                            captcha_visible: visibleCaptchaNodes.length > 0,
                            captcha_text: captchaText,
                            captcha_iframe_src: visibleCaptchaNodes
                                .map((el) => el.src || '')
                                .filter(Boolean)
                                .join(' | ')
                                .slice(0, 500),
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
                observed_result = _normalize_zhuque_observed_page_result(
                    observed_payloads=observed_result_payloads,
                    page_state=data,
                    text_length=len(text),
                )
                if observed_result is not None:
                    anonymous_fp = str(data.get("anonymous_fp") or data.get("fp") or "").strip()
                    if anonymous and anonymous_fp:
                        observed_result.update(
                            {
                                "fp": anonymous_fp,
                                "anonymous_fp": anonymous_fp,
                                "has_anonymous_fp": True,
                            }
                        )
                    return observed_result
                if _zhuque_page_captcha_detected(data):
                    captcha_seen = True
                    if not captcha_artifact_written:
                        await self._write_quota_probe_artifacts(
                            page,
                            reason=(
                                "detect_captcha_required"
                                if self._browser_headless
                                else "detect_captcha_waiting_for_visible_browser"
                            ),
                            quota_state={
                                "captcha_text": data.get("captcha_text") or "",
                                "captcha_iframe_src": data.get("captcha_iframe_src") or "",
                                "button_text": data.get("button_text") or "",
                                "alert_title": data.get("alert_title") or "",
                                "headless": self._browser_headless,
                            },
                        )
                        captcha_artifact_written = True
                    if self._browser_headless:
                        return _captcha_required_zhuque_result(
                            "朱雀触发腾讯验证码，请打开朱雀验证窗口，在真实浏览器手动完成验证后回到本页继续处理",
                            len(text),
                        )
                    if not captcha_deadline_extended:
                        deadline = max(deadline, time.time() + _zhuque_visible_captcha_wait_seconds())
                        captcha_deadline_extended = True
                    # Visible local detection window: keep the same page alive so
                    # the user can complete Tencent CAPTCHA and the existing
                    # WebSocket/HTTP payload listeners can capture the terminal
                    # result without losing browser continuity.
                    continue
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

            if captcha_seen:
                return _captcha_required_zhuque_result(
                    "朱雀腾讯验证码在可见检测窗口中仍未完成，请完成验证后点击继续/重试",
                    len(text),
                )
            return self._failure(f"朱雀真实页面检测超时 ({timeout}s)", len(text))
        except Exception as exc:
            message = str(exc)
            if "Target page" in message or "Browser has been closed" in message or "context" in message.lower():
                await self._close_persistent_page_context()
                self._browser = None
            return self._failure(f"朱雀真实页面检测失败: {exc}", len(text))
        finally:
            self._last_detect_time = time.time()
            if page is not None and self._browser_context is not None:
                page_closed = True
                with contextlib.suppress(Exception):
                    page_closed = page.is_closed()
                if not page_closed:
                    self._cached_page = page

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
            page_kwargs: dict = {
                "reason": f"未找到可用 token，尝试使用朱雀页面未登录免费次数: {exc}",
                "anonymous": True,
            }
        else:
            if not creds.get("access_token"):
                page_kwargs = {
                    "reason": "朱雀凭证缺少 access_token，尝试使用真实页面未登录免费次数",
                    "anonymous": True,
                }
            else:
                page_kwargs = {
                    "reason": "朱雀 WebSocket 验证码绕过已失效，直接使用真实页面检测",
                    "anonymous": False,
                }

        last_result = None
        for attempt in range(3):
            result = await self._detect_with_page(text, timeout, **page_kwargs)
            if result.get("success"):
                self._last_detect_failed = False
                return result
            last_result = result
            message = str(result.get("message") or "")
            retryable = _zhuque_detect_failure_retryable(message)
            if not retryable:
                self._last_detect_failed = False
                return result
            if attempt < 2:
                self._last_detect_failed = True
                logger.info("朱雀真实页面检测超时/断连，重试 %s/3（等待冷却）", attempt + 2)
                continue
        self._last_detect_failed = True
        return last_result or self._failure(f"朱雀真实页面检测超时 ({timeout}s)", text_len)

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
