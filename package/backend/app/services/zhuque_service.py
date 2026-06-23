"""
朱雀检测服务 — 微信扫码凭证 + 无头 API 串行检测队列
"""
import asyncio
import logging
import time
from uuid import uuid4
from typing import List, Dict, Optional, Callable, Any
from app.services.zhuque_api import ZhuqueAPI
from app.config import settings

logger = logging.getLogger(__name__)

ZHUQUE_QUOTA_REFRESH_INTERVAL_SECONDS = 15.0


class ZhuqueService:
    """单例: 管理朱雀无头 API 凭证 + 序列化检测请求"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.api: Optional[ZhuqueAPI] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ready: bool = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._last_remaining_uses: Optional[int] = None
        self._last_remaining_checked_at: float = 0.0
        self._initialized = True

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

    async def _refresh_live_remaining_uses(
        self,
        api: ZhuqueAPI,
        *,
        current_remaining: int = -1,
        force: bool = False,
        timeout: float = 2.5,
    ) -> int:
        """Refresh Zhuque quota through a no-text WebSocket auth probe.

        The value stored in creds_latest.json is captured at login time and can
        become stale. This probe only sends auth data and closes before captcha
        or text submission, so it does not consume a detection use.
        """
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
            return self._last_remaining_uses if self._last_remaining_uses is not None else current_remaining

        self._last_remaining_checked_at = now
        live_remaining = await peek_remaining(timeout=timeout)
        remembered = self._remember_remaining_uses(live_remaining)
        if remembered >= 0:
            return remembered
        return self._last_remaining_uses if self._last_remaining_uses is not None else current_remaining

    def _ensure_api(self) -> ZhuqueAPI:
        if self.api is None:
            self.api = ZhuqueAPI(debug=False)
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

    async def start(self) -> None:
        """启动服务: 校验微信扫码凭证, 启动消费循环"""
        if self._ready:
            return
        api = self._ensure_api()
        status = await api.status()
        has_token = bool(status.get("has_token"))
        if not status.get("ready") and not status.get("button_enabled", True):
            raise RuntimeError(status.get("message") or "朱雀微信扫码凭证不可用")
        if has_token:
            status["remaining_uses"] = await self._refresh_live_remaining_uses(
                api,
                current_remaining=status.get("remaining_uses"),
                force=True,
                timeout=2.5,
            )
        self._ready = True
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer())
        logger.info(
            "[ZhuqueService] 无头 API 就绪 | logged_in=%s | remaining=%s | user=%s | Token: %s...",
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
                result = await self.api.detect(text, timeout=settings.ZHUQUE_DETECT_TIMEOUT)
                self._remember_remaining_uses(result.get("remaining_uses"))
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

    async def detect(self, text: str) -> dict:
        """入队检测, 返回结果"""
        if not self._ready:
            await self.start()
        future: asyncio.Future = asyncio.Future()
        task_id = str(uuid4())
        await self._queue.put((task_id, text, future))
        return await future

    async def readiness(self, text: Optional[str] = None) -> dict:
        """读取朱雀微信凭证状态，不发起检测，不消耗朱雀次数。"""
        text_length = len(text or "") if text is not None else None
        text_length_ok = True if text is None else text_length >= 350
        base = {
            "ready": False,
            "connected": False,
            "page_found": False,
            "has_token": False,
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

        status = self._ensure_api().credential_status()
        api = self._ensure_api()
        has_token = bool(status.get("has_token"))
        credential_remaining_uses = self._coerce_remaining_uses(status.get("remaining_uses"))
        remaining_uses = credential_remaining_uses
        if has_token:
            remaining_uses = await self._refresh_live_remaining_uses(
                api,
                current_remaining=credential_remaining_uses,
                force=bool(text is not None and text_length_ok),
                timeout=2.5,
            )

        can_use_free_quota = remaining_uses != 0
        ready = text_length_ok and can_use_free_quota
        actions = []
        if not has_token:
            actions.append("可直接使用朱雀未登录免费次数，或微信扫码登录获取账号次数")
        if not text_length_ok:
            actions.append("补充文本到 350 字以上")
        if remaining_uses == 0:
            actions.append("切换朱雀微信账号或等待次数恢复")

        if ready:
            message = "朱雀无头 API 已就绪" if has_token else "朱雀未登录，可尝试使用免费检测次数"
        elif not text_length_ok:
            message = f"文本长度不足 350 字，当前 {text_length} 字"
        elif remaining_uses == 0:
            message = "朱雀剩余次数不足，请切换微信账号或等待次数恢复"
        else:
            message = status.get("message") or "未找到朱雀微信扫码凭证"

        return {
            **base,
            **status,
            "ready": ready,
            "connected": has_token,
            "page_found": bool(status.get("page_found")) or has_token,
            "has_token": has_token,
            "remaining_uses": remaining_uses,
            "button_enabled": can_use_free_quota,
            "text_length": text_length,
            "text_length_ok": text_length_ok,
            "message": message,
            "actions": actions,
        }

    async def detect_segments(
        self,
        segments: List[Any],
        progress_callback: Optional[Callable] = None,
    ) -> List[dict]:
        """批量检测段落, 返回高AI段落结果列表"""
        results = []
        for i, seg in enumerate(segments):
            text = getattr(seg, "original_text", str(seg))
            result = await self.detect(text)
            results.append(result)
            if progress_callback:
                await progress_callback(i, len(segments), result)
            # 频率控制
            interval = max(settings.ZHUQUE_DETECT_INTERVAL, 0.1)
            if interval > 0 and i < len(segments) - 1:
                await asyncio.sleep(interval)
        return results

    @property
    def is_ready(self) -> bool:
        return self._ready


# 全局单例
zhuque_service = ZhuqueService()
