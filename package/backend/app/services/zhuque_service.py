"""
朱雀检测服务 — 微信扫码凭证 + 无头 API 串行检测队列
"""
import asyncio
import logging
from uuid import uuid4
from typing import List, Dict, Optional, Callable, Any
from app.services.zhuque_api import ZhuqueAPI
from app.config import settings

logger = logging.getLogger(__name__)


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
        self._initialized = True

    def _ensure_api(self) -> ZhuqueAPI:
        if self.api is None:
            self.api = ZhuqueAPI(debug=False)
        return self.api

    async def start(self) -> None:
        """启动服务: 校验微信扫码凭证, 启动消费循环"""
        if self._ready:
            return
        api = self._ensure_api()
        status = await api.status()
        if not status.get("ready"):
            raise RuntimeError(status.get("message") or "朱雀微信扫码凭证不可用")
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
        remaining_uses = status.get("remaining_uses", -1)
        try:
            remaining_uses = int(remaining_uses)
        except (TypeError, ValueError):
            remaining_uses = -1

        has_token = bool(status.get("has_token"))
        ready = has_token and text_length_ok and remaining_uses != 0
        actions = []
        if not has_token:
            actions.append("微信扫码登录朱雀")
        if not text_length_ok:
            actions.append("补充文本到 350 字以上")
        if remaining_uses == 0:
            actions.append("切换朱雀微信账号或等待次数恢复")

        if ready:
            message = "朱雀无头 API 已就绪"
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
            "page_found": has_token,
            "has_token": has_token,
            "remaining_uses": remaining_uses,
            "button_enabled": has_token,
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
