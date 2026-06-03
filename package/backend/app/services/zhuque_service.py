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

    async def start(self) -> None:
        """启动服务: 连接Chrome, 启动消费循环"""
        if self._ready:
            return
        self.api = ZhuqueAPI(cdp_port=settings.ZHUQUE_CDP_PORT, debug=False)
        status = await self.api.status()
        if not status.get("has_token"):
            raise RuntimeError(
                "Chrome未登录朱雀。请打开 https://matrix.tencent.com/ai-detect/ 完成登录"
            )
        self._ready = True
        self._consumer_task = asyncio.create_task(self._consumer())
        logger.info(
            "[ZhuqueService] 就绪 | Token: %s...",
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
