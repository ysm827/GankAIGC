"""
朱雀检测服务 — 微信扫码凭证 + 无头 API 串行检测队列
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from uuid import uuid4
from typing import List, Optional, Callable, Any

from app.services.zhuque_api import ZhuqueAPI
from app.config import settings

logger = logging.getLogger(__name__)

ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS = 15.0


def _recent_quota_cache_valid(last_checked_at: float) -> bool:
    return (
        last_checked_at > 0
        and time.monotonic() - last_checked_at < ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS
    )


def zhuque_user_data_root() -> Path:
    """Return the root directory for per-user Zhuque credentials/runtime state."""
    configured = getattr(settings, "ZHUQUE_USER_DATA_DIR", "") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[4] / "zhuque_pkg" / "users"


def zhuque_user_dir(user_id: int | str) -> Path:
    safe_user_id = str(user_id).strip()
    if not safe_user_id.isdigit():
        raise ValueError("user_id must be numeric for Zhuque credential isolation")
    return zhuque_user_data_root() / f"user_{safe_user_id}"


def zhuque_user_credentials_file(user_id: int | str) -> Path:
    return zhuque_user_dir(user_id) / "creds_latest.json"


class ZhuqueService:
    """Per-credential Zhuque API service with serialized detect queue."""

    def __init__(self, *, credentials_file: str | Path | None = None, owner_label: str = "global"):
        self.credentials_file = Path(credentials_file).expanduser() if credentials_file else None
        self.owner_label = owner_label
        self.api: Optional[ZhuqueAPI] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ready: bool = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._last_remaining_uses: Optional[int] = None
        self._last_remaining_checked_at: float = 0.0

    def _coerce_remaining_uses(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def _remember_remaining_uses(self, value) -> int:
        """Cache the latest known live Zhuque quota; -1 means unknown."""
        remaining_uses = self._coerce_remaining_uses(value)
        if remaining_uses >= 0:
            self._last_remaining_uses = remaining_uses
            self._last_remaining_checked_at = time.monotonic()
        return remaining_uses

    def cached_remaining_uses(self) -> Optional[int]:
        """Return the latest live Zhuque quota observed by this service.

        The credential/session files may lag behind Zhuque after a detection or
        a no-text quota refresh. Passive status/readiness polling should not
        overwrite a fresher live value with that stale persisted count.
        """
        return self._last_remaining_uses

    async def _refresh_live_remaining_uses(
        self,
        api: ZhuqueAPI,
        *,
        current_remaining: int = -1,
        force: bool = False,
        timeout: float = 2.5,
        allow_anonymous: bool = False,
        allow_stale_fallback: bool = True,
    ) -> int:
        """Refresh Zhuque quota through a no-text WebSocket auth probe."""
        current_remaining = self._coerce_remaining_uses(current_remaining)
        now = time.monotonic()
        if (
            not force
            and self._last_remaining_uses is not None
            and self._last_remaining_checked_at > 0
            and now - self._last_remaining_checked_at < ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS
        ):
            return self._last_remaining_uses

        peek_remaining = getattr(api, "peek_remaining_uses", None)
        if not callable(peek_remaining):
            if allow_stale_fallback:
                return self._last_remaining_uses if self._last_remaining_uses is not None else current_remaining
            self._last_remaining_uses = None
            self._last_remaining_checked_at = 0.0
            return -1

        self._last_remaining_checked_at = now
        try:
            live_remaining = await peek_remaining(timeout=timeout, allow_anonymous=allow_anonymous)
        except TypeError:
            live_remaining = await peek_remaining(timeout=timeout)
        remembered = self._remember_remaining_uses(live_remaining)
        if remembered >= 0:
            return remembered
        if not allow_stale_fallback:
            self._last_remaining_uses = None
            self._last_remaining_checked_at = 0.0
            return -1
        return self._last_remaining_uses if self._last_remaining_uses is not None else current_remaining


    def _quota_status_from_payload(self, payload: dict | None) -> dict:
        payload = payload or {}
        remaining_uses = self._coerce_remaining_uses(payload.get("remaining_uses"))
        button_enabled = bool(payload.get("button_enabled"))
        return {
            "remaining_uses": remaining_uses,
            "button_enabled": button_enabled if remaining_uses < 0 else remaining_uses > 0,
            "page_found": bool(payload.get("page_found")) or button_enabled or remaining_uses >= 0,
            "quota_text": payload.get("quota_text", "") or (f"剩余 {remaining_uses} 次" if remaining_uses >= 0 else ""),
            "message": payload.get("message", ""),
            "probe_state": payload.get("probe_state") or {},
            "anonymous_fp": str(payload.get("anonymous_fp") or payload.get("fp") or "").strip(),
            "has_anonymous_fp": bool(payload.get("has_anonymous_fp") or payload.get("anonymous_fp") or payload.get("fp")),
        }

    async def _refresh_live_quota_status(
        self,
        api: ZhuqueAPI,
        *,
        current_remaining: int = -1,
        force: bool = False,
        timeout: float = 2.5,
        allow_anonymous: bool = False,
        allow_stale_fallback: bool = True,
    ) -> dict:
        """Refresh Zhuque quota and preserve anonymous button availability.

        A negative remaining count means the numeric quota is hidden/unknown,
        not necessarily unusable. Current Zhuque anonymous pages can show a
        clickable `Detect now` button while hiding the count, so callers need
        both `remaining_uses` and `button_enabled`.
        """
        current_remaining = self._coerce_remaining_uses(current_remaining)
        now = time.monotonic()
        if (
            not force
            and self._last_remaining_uses is not None
            and self._last_remaining_checked_at > 0
            and now - self._last_remaining_checked_at < ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS
        ):
            return {
                "remaining_uses": self._last_remaining_uses,
                "button_enabled": self._last_remaining_uses > 0,
                "page_found": True,
                "quota_text": f"剩余 {self._last_remaining_uses} 次",
                "message": "使用最近一次朱雀剩余次数缓存",
                "probe_state": {},
            }

        peek_quota_status = getattr(api, "peek_quota_status", None)
        if callable(peek_quota_status):
            self._last_remaining_checked_at = now
            try:
                live_status = await peek_quota_status(timeout=timeout, allow_anonymous=allow_anonymous)
            except TypeError:
                live_status = await peek_quota_status(timeout=timeout)
            quota_status = self._quota_status_from_payload(live_status)
            remembered = self._remember_remaining_uses(quota_status["remaining_uses"])
            if remembered >= 0:
                quota_status["remaining_uses"] = remembered
                quota_status["button_enabled"] = remembered > 0
                return quota_status
            if quota_status["button_enabled"]:
                self._last_remaining_uses = None
                self._last_remaining_checked_at = 0.0
                return quota_status
            if not allow_stale_fallback:
                self._last_remaining_uses = None
                self._last_remaining_checked_at = 0.0
                return quota_status
            if self._last_remaining_uses is not None:
                return {
                    "remaining_uses": self._last_remaining_uses,
                    "button_enabled": self._last_remaining_uses > 0,
                    "page_found": True,
                    "quota_text": f"剩余 {self._last_remaining_uses} 次",
                    "message": "使用最近一次朱雀剩余次数缓存",
                    "probe_state": {},
                }
            if current_remaining >= 0:
                return {
                    "remaining_uses": current_remaining,
                    "button_enabled": current_remaining > 0,
                    "page_found": True,
                    "quota_text": f"剩余 {current_remaining} 次",
                    "message": "使用当前朱雀剩余次数",
                    "probe_state": {},
                }
            return quota_status

        remaining_uses = await self._refresh_live_remaining_uses(
            api,
            current_remaining=current_remaining,
            force=force,
            timeout=timeout,
            allow_anonymous=allow_anonymous,
            allow_stale_fallback=allow_stale_fallback,
        )
        return {
            "remaining_uses": remaining_uses,
            "button_enabled": remaining_uses > 0 if remaining_uses >= 0 else False,
            "page_found": remaining_uses >= 0,
            "quota_text": f"剩余 {remaining_uses} 次" if remaining_uses >= 0 else "",
            "message": "朱雀剩余次数已同步" if remaining_uses >= 0 else "暂未探测到朱雀剩余次数",
            "probe_state": {},
        }

    def _anonymous_fp_from_api(
        self,
        api: ZhuqueAPI,
        status: dict | None = None,
        quota_status: dict | None = None,
    ) -> str:
        """Return persisted anonymous fp without treating it as login credentials."""
        if isinstance(quota_status, dict):
            fp = str(quota_status.get("anonymous_fp") or quota_status.get("fp") or "").strip()
            if fp:
                return fp
            probe_state = quota_status.get("probe_state")
            if isinstance(probe_state, dict):
                fp = str(probe_state.get("anonymous_fp") or probe_state.get("fp") or "").strip()
                if fp:
                    return fp
        if isinstance(status, dict) and not status.get("has_token"):
            fp = str(status.get("anonymous_fp") or status.get("fp") or "").strip()
            if fp:
                return fp
        load_credentials = getattr(api, "load_credentials", None)
        if not callable(load_credentials):
            return ""
        try:
            creds = load_credentials(refresh=False)
        except RuntimeError:
            return ""
        if creds.get("access_token"):
            return ""
        return str(creds.get("fp") or "").strip()

    def _write_logged_out_quota_status(
        self,
        api: ZhuqueAPI,
        remaining_uses: int,
        message: str,
        quota_status: dict | None = None,
    ) -> None:
        """Persist non-secret logged-out quota UI state for the current user."""
        status_file = Path(api.credentials_file).parent / "session_status.json"
        existing_status = {}
        if status_file.exists():
            try:
                existing_status = json.loads(status_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing_status = {}
        anonymous_fp = self._anonymous_fp_from_api(
            api,
            existing_status if isinstance(existing_status, dict) else None,
            quota_status,
        )
        if not anonymous_fp:
            if isinstance(existing_status, dict) and not existing_status.get("has_token"):
                anonymous_fp = str(existing_status.get("anonymous_fp") or existing_status.get("fp") or "").strip()
        if remaining_uses < 0 and not anonymous_fp:
            return
        payload = {
            "connected": False,
            "ready": False,
            "has_token": False,
            "has_anonymous_fp": bool(anonymous_fp),
            "anonymous_fp": anonymous_fp,
            "remaining_uses": remaining_uses,
            "user_name": "",
            "quota_text": f"剩余 {remaining_uses} 次" if remaining_uses >= 0 else "",
            "message": message,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            status_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = status_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            tmp_file.replace(status_file)
        except OSError:
            logger.warning(
                "[ZhuqueService:%s] Failed to persist logged-out Zhuque quota status",
                self.owner_label,
                exc_info=True,
            )

    def _ensure_api(self) -> ZhuqueAPI:
        if self.api is None:
            self.api = ZhuqueAPI(debug=False, credentials_file=self.credentials_file)
        return self.api

    def reset_credentials_state(self) -> None:
        """Reset cached Zhuque auth/quota state after a credential switch/logout."""
        if self.api is not None:
            forget_cache = getattr(self.api, "forget_credentials_cache", None)
            if callable(forget_cache):
                forget_cache()
        self._ready = False
        self._last_remaining_uses = None
        self._last_remaining_checked_at = 0.0

    def _should_reset_after_detect_failure(self, result: dict) -> bool:
        """Return whether a failed Zhuque detect likely invalidated auth state."""
        if not isinstance(result, dict) or result.get("success") is not False:
            return False
        message = str(result.get("message") or result.get("alert_text") or "").lower()
        if not message:
            return False
        transient_markers = (
            "超时",
            "timeout",
            "timed out",
            "网络",
            "network",
            "验证码",
            "captcha",
            "diff",
        )
        if any(marker in message for marker in transient_markers):
            return False
        reset_markers = (
            "登录已过期",
            "重新微信扫码登录",
            "重新扫码",
            "未找到朱雀微信登录凭证",
            "凭证缺少",
            "凭证不可用",
            "token",
            "access_token",
            "unauthorized",
            "401",
            "403",
            "reauth",
        )
        return any(marker in message for marker in reset_markers)

    def _ensure_consumer_task(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer())

    async def start(self) -> None:
        """启动服务: 校验微信扫码凭证或匿名免费检测能力，启动消费循环。"""
        if self._ready:
            self._ensure_consumer_task()
            return
        api = self._ensure_api()
        status = await api.status()
        has_token = bool(status.get("has_token"))
        if not status.get("ready") and not status.get("button_enabled", True):
            raise RuntimeError(status.get("message") or "朱雀微信扫码凭证不可用")
        quota_status = await self._refresh_live_quota_status(
            api,
            current_remaining=status.get("remaining_uses"),
            force=False,
            timeout=2.5 if has_token else 5.0,
            allow_anonymous=not has_token,
            allow_stale_fallback=False,
        )
        status.update({k: v for k, v in quota_status.items() if k in {"remaining_uses", "button_enabled", "page_found", "quota_text", "message"}})
        remaining_uses = self._coerce_remaining_uses(status.get("remaining_uses"))
        button_enabled = bool(status.get("button_enabled"))
        if remaining_uses == 0 or (remaining_uses < 0 and not button_enabled):
            if remaining_uses == 0:
                raise RuntimeError("朱雀剩余次数不足，请切换微信账号或等待次数恢复")
            raise RuntimeError("暂未探测到朱雀剩余次数，请先点击刷新次数或扫码登录后再开始检测")
        self._remember_remaining_uses(remaining_uses)
        self._ready = True
        self._ensure_consumer_task()
        logger.info(
            "[ZhuqueService:%s] 无头 API 就绪 | logged_in=%s | remaining=%s | user=%s | Token: %s...",
            self.owner_label,
            bool(status.get("has_token")),
            status.get("remaining_uses"),
            status.get("user_name", ""),
            status.get("token_preview", "")[:10],
        )

    async def _consumer(self) -> None:
        """后台消费: 串行处理检测队列，避免朱雀侧限流。"""
        while True:
            task_id, text, future = await self._queue.get()
            try:
                if future.done():
                    continue
                before_remaining = self._last_remaining_uses
                try:
                    credential_status = self.api.credential_status()
                except Exception:
                    credential_status = {}
                detection_used_anonymous = not bool(credential_status.get("has_token"))
                result = await self.api.detect(text, timeout=settings.ZHUQUE_DETECT_TIMEOUT)
                if self._should_reset_after_detect_failure(result):
                    self.reset_credentials_state()
                if (
                    result.get("success")
                    and self._coerce_remaining_uses(result.get("remaining_uses")) < 0
                    and before_remaining is not None
                    and before_remaining > 0
                ):
                    result = {
                        **result,
                        "remaining_uses": max(before_remaining - 1, 0),
                    }
                self._remember_remaining_uses(result.get("remaining_uses"))
                if result.get("success") and detection_used_anonymous:
                    remaining_uses = self._coerce_remaining_uses(result.get("remaining_uses"))
                    anonymous_fp = self._anonymous_fp_from_api(self.api, credential_status, result)
                    if remaining_uses >= 0 or anonymous_fp:
                        quota_status = {
                            **result,
                            "anonymous_fp": anonymous_fp or str(result.get("anonymous_fp") or result.get("fp") or "").strip(),
                            "has_anonymous_fp": bool(anonymous_fp or result.get("anonymous_fp") or result.get("fp")),
                        }
                        message = (
                            f"朱雀免费次数已同步：{remaining_uses} 次"
                            if remaining_uses >= 0
                            else "朱雀免费检测入口可用，剩余次数将在检测后同步"
                        )
                        self._write_logged_out_quota_status(self.api, remaining_uses, message, quota_status)
                        forget_cache = getattr(self.api, "forget_credentials_cache", None)
                        if callable(forget_cache):
                            forget_cache()
                if not future.done():
                    future.set_result(result)
            except Exception as e:
                logger.warning(
                    "[ZhuqueService:%s] detect task %s failed: %s",
                    self.owner_label,
                    task_id,
                    e,
                )
                if not future.done():
                    future.set_exception(e)
            finally:
                self._queue.task_done()

    async def detect(self, text: str) -> dict:
        """入队检测, 返回结果。"""
        if not self._ready:
            await self.start()
        else:
            self._ensure_consumer_task()
        future: asyncio.Future = asyncio.Future()
        task_id = str(uuid4())
        await self._queue.put((task_id, text, future))
        return await future

    async def close(self) -> None:
        """Stop the consumer and close persistent Zhuque browser resources."""
        if self._consumer_task is not None and not self._consumer_task.done():
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
        self._consumer_task = None
        if self.api is not None:
            close_api = getattr(self.api, "close", None)
            if callable(close_api):
                await close_api()

    async def readiness(self, text: Optional[str] = None) -> dict:
        """读取朱雀微信凭证状态，不发起检测，不消耗朱雀次数。"""
        text_length = len(text or "") if text is not None else None
        text_length_ok = True if text is None else text_length >= 350
        base = {
            "ready": False,
            "connected": False,
            "page_found": False,
            "has_token": False,
            "has_anonymous_fp": False,
            "remaining_uses": -1,
            "button_enabled": False,
            "text_length": text_length,
            "text_length_ok": text_length_ok,
            "estimated_first_round_credits": 10 if text else 0,
            "estimated_max_round_credits": (10 * settings.ZHUQUE_MAX_REDUCE_ROUNDS) if text else 0,
            "message": "",
            "actions": [],
            "auth_mode": "headless_api",
            "login_mode": "wechat_qr",
            "credential_file": "",
            "user_name": "",
            "quota_text": "",
            "captured_at": "",
        }

        api = self._ensure_api()
        status = api.credential_status()
        has_token = bool(status.get("has_token"))
        has_anonymous_fp = bool(status.get("has_anonymous_fp") or (not has_token and self._anonymous_fp_from_api(api, status)))
        credential_remaining_uses = self._coerce_remaining_uses(status.get("remaining_uses"))
        remaining_uses = credential_remaining_uses
        button_enabled = bool(status.get("button_enabled"))
        page_found = bool(status.get("page_found"))
        quota_text = status.get("quota_text", "") or ""
        live_quota_status = None
        if has_token:
            # Passive workspace polling and invalid-short-text preflight must stay
            # instant. Only a valid task text forces a live no-text WebSocket probe.
            force_live_probe = bool(text is not None and text_length_ok)
            if not force_live_probe:
                if self._last_remaining_uses is not None:
                    remaining_uses = self._last_remaining_uses
                    button_enabled = remaining_uses > 0
                elif credential_remaining_uses >= 0:
                    remaining_uses = credential_remaining_uses
                    button_enabled = remaining_uses > 0
                    self._remember_remaining_uses(credential_remaining_uses)
                else:
                    remaining_uses = -1
                    button_enabled = bool(status.get("button_enabled", True))
            else:
                live_quota_status = await self._refresh_live_quota_status(
                    api,
                    current_remaining=credential_remaining_uses,
                    force=force_live_probe,
                    timeout=2.5,
                    allow_stale_fallback=not force_live_probe,
                )
                remaining_uses = live_quota_status["remaining_uses"]
                button_enabled = live_quota_status["button_enabled"]
                page_found = page_found or live_quota_status["page_found"]
                quota_text = live_quota_status.get("quota_text") or quota_text
        elif text is not None and text_length_ok:
            live_quota_status = await self._refresh_live_quota_status(
                api,
                current_remaining=credential_remaining_uses,
                force=True,
                timeout=5.0,
                allow_anonymous=True,
                allow_stale_fallback=False,
            )
            remaining_uses = live_quota_status["remaining_uses"]
            button_enabled = live_quota_status["button_enabled"]
            page_found = page_found or live_quota_status["page_found"]
            quota_text = live_quota_status.get("quota_text") or quota_text
            has_anonymous_fp = bool(
                has_anonymous_fp
                or (not has_token and self._anonymous_fp_from_api(api, status, live_quota_status))
            )
        elif self._last_remaining_uses is not None:
            remaining_uses = self._last_remaining_uses
            button_enabled = remaining_uses > 0
        elif credential_remaining_uses >= 0:
            remaining_uses = credential_remaining_uses
            button_enabled = remaining_uses > 0
            self._remember_remaining_uses(credential_remaining_uses)

        can_use_quota = remaining_uses > 0 or (remaining_uses < 0 and button_enabled)
        ready = text_length_ok and remaining_uses != 0 and can_use_quota
        actions = []
        if not has_token:
            if remaining_uses > 0:
                actions.append("可直接使用朱雀未登录免费次数，或微信扫码登录获取账号次数")
            elif button_enabled:
                actions.append("朱雀免费检测入口可用，剩余次数将在检测后同步")
                actions.append("也可微信扫码登录获取账号次数")
            else:
                actions.append("点击刷新次数检测朱雀免费次数，或微信扫码登录获取账号次数")
        elif remaining_uses < 0 and text_length_ok and not button_enabled:
            actions.append("刷新次数后再开始任务")
            actions.append("重新扫码登录朱雀")
        if not text_length_ok:
            actions.append("补充文本到 350 字以上")
        if remaining_uses == 0:
            actions.append("切换朱雀微信账号或等待次数恢复")
        if not has_token and remaining_uses < 0 and text_length_ok and not button_enabled:
            actions.append("刷新次数后再开始任务")

        if ready:
            if remaining_uses < 0:
                message = "朱雀微信凭证已就绪，剩余次数将在检测后同步" if has_token else "朱雀免费检测入口可用，剩余次数将在检测后同步"
            else:
                message = "朱雀无头 API 已就绪" if has_token else "朱雀未登录，可尝试使用免费检测次数"
        elif not text_length_ok:
            message = f"文本长度不足 350 字，当前 {text_length} 字"
        elif remaining_uses == 0:
            message = "朱雀剩余次数不足，请切换微信账号或等待次数恢复"
        elif remaining_uses < 0:
            message = (
                "暂未探测到朱雀剩余次数；请点击刷新次数或重新扫码登录后再开始任务"
                if has_token
                else "暂未探测到朱雀免费次数；请点击刷新次数或扫码登录后再开始任务"
            )
        else:
            message = status.get("message") or "未找到朱雀微信扫码凭证"

        return {
            **base,
            **status,
            "ready": ready,
            "connected": has_token,
            "page_found": page_found or has_token or can_use_quota,
            "has_token": has_token,
            "has_anonymous_fp": has_anonymous_fp,
            "remaining_uses": remaining_uses,
            "button_enabled": can_use_quota,
            "text_length": text_length,
            "text_length_ok": text_length_ok,
            "message": message,
            "actions": actions,
            "quota_text": quota_text,
        }

    async def refresh_free_quota(self, timeout: float = 5.0) -> dict:
        """Force-refresh live Zhuque remaining uses without submitting text."""
        api = self._ensure_api()
        status = api.credential_status()
        has_token = bool(status.get("has_token"))
        current_remaining = self._coerce_remaining_uses(status.get("remaining_uses"))
        quota_status = await self._refresh_live_quota_status(
            api,
            current_remaining=current_remaining,
            force=True,
            timeout=timeout,
            allow_anonymous=True,
            allow_stale_fallback=False,
        )
        remaining_uses = quota_status["remaining_uses"]
        button_enabled = bool(quota_status["button_enabled"])
        ready = remaining_uses != 0 and button_enabled
        if remaining_uses >= 0:
            message = (
                f"朱雀账号剩余次数已同步：{remaining_uses} 次"
                if has_token
                else f"朱雀免费次数已同步：{remaining_uses} 次"
            )
        elif button_enabled:
            message = (
                "朱雀账号检测入口可用，剩余次数将在检测后同步"
                if has_token
                else "朱雀免费检测入口可用，剩余次数将在检测后同步"
            )
        else:
            message = (
                "暂未探测到朱雀账号剩余次数；请重新扫码登录或稍后重试，当前不能开始朱雀检测"
                if has_token
                else "暂未探测到朱雀免费次数；请稍后重试或扫码登录，当前不能开始朱雀检测"
            )

        if not has_token and (
            remaining_uses >= 0
            or self._anonymous_fp_from_api(api, status, quota_status)
        ):
            self._write_logged_out_quota_status(api, remaining_uses, message, quota_status)

        return {
            "ready": ready,
            "connected": has_token,
            "page_found": bool(status.get("page_found")) or has_token or quota_status["page_found"] or ready,
            "has_token": has_token,
            "has_anonymous_fp": bool(status.get("has_anonymous_fp") or (not has_token and self._anonymous_fp_from_api(api, status, quota_status))),
            "remaining_uses": remaining_uses,
            "button_enabled": button_enabled,
            "text_length": None,
            "text_length_ok": True,
            "estimated_first_round_credits": 0,
            "estimated_max_round_credits": 0,
            "message": message,
            "actions": (
                []
                if remaining_uses > 0
                else ["切换朱雀微信账号或等待次数恢复"] if remaining_uses == 0
                else ["可直接开始检测，剩余次数检测后同步"] if button_enabled
                else ["稍后刷新次数", "扫码登录朱雀"]
            ),
            "auth_mode": status.get("auth_mode", "headless_api"),
            "login_mode": status.get("login_mode", "wechat_qr"),
            "credential_file": status.get("credential_file", str(api.credentials_file)),
            "user_name": status.get("user_name", "") if has_token else "",
            "quota_text": quota_status.get("quota_text") or status.get("quota_text", "") or (f"剩余 {remaining_uses} 次" if remaining_uses >= 0 else ""),
            "captured_at": status.get("captured_at", ""),
        }

    async def detect_segments(
        self,
        segments: List[Any],
        progress_callback: Optional[Callable] = None,
    ) -> List[dict]:
        """批量检测段落, 返回高AI段落结果列表。"""
        results = []
        for i, seg in enumerate(segments):
            text = getattr(seg, "original_text", str(seg))
            result = await self.detect(text)
            results.append(result)
            if progress_callback:
                await progress_callback(i, len(segments), result)
            interval = max(settings.ZHUQUE_DETECT_INTERVAL, 0.1)
            if interval > 0 and i < len(segments) - 1:
                await asyncio.sleep(interval)
        return results

    @property
    def is_ready(self) -> bool:
        return self._ready


class ZhuqueServiceManager:
    """Keeps one serialized ZhuqueService per GankAIGC user."""

    def __init__(self):
        self._services: dict[int, ZhuqueService] = {}
        self._legacy_service = ZhuqueService(owner_label="legacy")

    def for_user(self, user_id: int | str | None) -> ZhuqueService:
        if user_id is None:
            return self._legacy_service
        numeric_user_id = int(user_id)
        service = self._services.get(numeric_user_id)
        if service is None:
            service = ZhuqueService(
                credentials_file=zhuque_user_credentials_file(numeric_user_id),
                owner_label=f"user_{numeric_user_id}",
            )
            self._services[numeric_user_id] = service
        return service

    def reset_user(self, user_id: int | str | None) -> None:
        self.for_user(user_id).reset_credentials_state()

    # Legacy passthroughs keep existing tests/imports usable until all callers
    # are migrated. New request/session code must call ``for_user(user.id)``.
    def _ensure_api(self) -> ZhuqueAPI:
        return self._legacy_service._ensure_api()

    def reset_credentials_state(self) -> None:
        self._legacy_service.reset_credentials_state()

    async def start(self) -> None:
        await self._legacy_service.start()

    async def detect(self, text: str) -> dict:
        return await self._legacy_service.detect(text)

    async def readiness(self, text: Optional[str] = None) -> dict:
        return await self._legacy_service.readiness(text)

    async def refresh_free_quota(self, timeout: float = 5.0) -> dict:
        return await self._legacy_service.refresh_free_quota(timeout=timeout)

    async def close(self) -> None:
        services = [self._legacy_service, *self._services.values()]
        await asyncio.gather(*(service.close() for service in services), return_exceptions=True)


# 全局管理器；每个用户隔离在 zhuque_pkg/users/user_<id>/ 下。
zhuque_service = ZhuqueServiceManager()
