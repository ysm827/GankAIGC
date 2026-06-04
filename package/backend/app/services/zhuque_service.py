"""
朱雀检测服务 — 单例浏览器管理器 + 异步检测队列
"""
import asyncio
import logging
from uuid import uuid4
from typing import List, Dict, Optional, Callable, Any
from app.services.zhuque_api import ZhuqueAPI
from app.config import settings

logger = logging.getLogger(__name__)


class ZhuqueService:
    """单例: 管理Chrome CDP连接 + 序列化检测请求"""

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
            self.api = ZhuqueAPI(cdp_port=settings.ZHUQUE_CDP_PORT, debug=False)
        return self.api

    async def start(self) -> None:
        """启动服务: 连接Chrome, 启动消费循环"""
        if self._ready:
            return
        api = self._ensure_api()
        status = await api.status()
        self._ready = True
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer())
        logger.info(
            "[ZhuqueService] 就绪 | logged_in=%s | remaining=%s | button=%s | Token: %s...",
            bool(status.get("has_token")),
            status.get("remaining_uses"),
            status.get("btn_text", ""),
            status.get("token_preview", "")[:10],
        )

    async def _consumer(self) -> None:
        """后台消费: 串行处理检测队列 (CDP限制)"""
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
        """读取朱雀页面状态, 不点击检测, 不消耗朱雀次数。"""
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
        }

        try:
            status = await self._ensure_api().status()
        except Exception as e:
            return {
                **base,
                "message": f"未连接到 Chrome CDP 端口 {settings.ZHUQUE_CDP_PORT} 或朱雀页面不可用: {e}",
                "actions": ["点击启动朱雀浏览器", "确认朱雀页面保持打开"],
            }

        url = status.get("url") or ""
        page_found = bool(status.get("page_found")) or "matrix.tencent.com/ai-detect" in url
        textarea_len = status.get("textarea_len", -1)
        try:
            textarea_len = int(textarea_len)
        except (TypeError, ValueError):
            textarea_len = -1
        textarea_present = bool(status.get("textarea_present")) or textarea_len >= 0
        submit_button_present = bool(status.get("submit_button_present", status.get("btn_text") not in (None, "NOT FOUND")))
        btn_disabled = status.get("btn_disabled")
        button_enabled = submit_button_present and btn_disabled is not True
        has_token = bool(status.get("has_token"))
        remaining_uses = status.get("remaining_uses", -1)
        try:
            remaining_uses = int(remaining_uses)
        except (TypeError, ValueError):
            remaining_uses = -1

        actions = []
        if not page_found:
            actions.append("打开朱雀 AI 检测页面")
        if not textarea_present:
            actions.append("等待朱雀页面加载完成")
        if not submit_button_present:
            actions.append("确认朱雀页面检测按钮已出现")
        if not text_length_ok:
            actions.append("补充文本到 350 字以上")
        if remaining_uses == 0 or (button_enabled is False and not has_token):
            actions.append("登录或切换朱雀账号")
        if button_enabled is False and remaining_uses != 0:
            actions.append("确认朱雀检测按钮可点击")

        ready = (
            page_found
            and textarea_present
            and button_enabled
            and text_length_ok
            and (remaining_uses != 0 or has_token)
        )

        if ready:
            message = "朱雀已就绪"
        elif not text_length_ok:
            message = f"文本长度不足 350 字，当前 {text_length} 字"
        elif remaining_uses == 0:
            message = "朱雀剩余次数不足，请登录或切换账号"
        elif not page_found:
            message = "未找到朱雀 AI 检测页面"
        elif not button_enabled:
            message = "朱雀检测按钮当前不可用"
        else:
            message = "朱雀尚未就绪"

        return {
            **base,
            "ready": ready,
            "connected": True,
            "page_found": page_found,
            "has_token": has_token,
            "remaining_uses": remaining_uses,
            "button_enabled": button_enabled,
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
