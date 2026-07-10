import asyncio
import contextlib
import json
import logging
from asyncio import Queue
from typing import Any, Dict, List

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal
from app.models.models import OptimizationSession, TaskEvent


logger = logging.getLogger(__name__)
TASK_EVENT_CHANNEL = "gankaigc_task_events"


class StreamManager:
    """Durable PostgreSQL-backed SSE event publisher and wake-up listener."""

    def __init__(self):
        self.connections: Dict[str, List[Queue]] = {}
        self._lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None

    async def connect(self, session_id: str) -> Queue:
        async with self._lock:
            queue: Queue = Queue(maxsize=256)
            self.connections.setdefault(session_id, []).append(queue)
            self._ensure_listener_locked()
            return queue

    async def disconnect(self, session_id: str, queue: Queue) -> None:
        async with self._lock:
            queues = self.connections.get(session_id)
            if not queues:
                return
            with contextlib.suppress(ValueError):
                queues.remove(queue)
            if not queues:
                del self.connections[session_id]

    async def close(self) -> None:
        async with self._lock:
            listener = self._listener_task
            self._listener_task = None
            self.connections.clear()
        if listener:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    def _ensure_listener_locked(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return
        self._listener_task = asyncio.create_task(self._listen_for_database_events())

    @staticmethod
    def _psycopg_database_url() -> str:
        url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
        return url.render_as_string(hide_password=False)

    async def _listen_for_database_events(self) -> None:
        while True:
            try:
                connection = await psycopg.AsyncConnection.connect(
                    self._psycopg_database_url(),
                    autocommit=True,
                )
                async with connection:
                    await connection.execute(
                        sql.SQL("LISTEN {}").format(sql.Identifier(TASK_EVENT_CHANNEL))
                    )
                    async for notification in connection.notifies():
                        try:
                            event_id = int(notification.payload)
                        except (TypeError, ValueError):
                            continue
                        await self._wake_connections(event_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Task event LISTEN failed; polling remains active: %s", exc)
                await asyncio.sleep(2)

    @staticmethod
    def _event_key(data: Dict[str, Any]) -> str | None:
        if data.get("type") != "content":
            return None
        segment_index = data.get("segment_index")
        stage = data.get("stage") or "unknown"
        return f"content:{segment_index}:{stage}"[:160]

    @staticmethod
    def _persist_event(session_id: str, data: Dict[str, Any]) -> int:
        db = SessionLocal()
        try:
            session = (
                db.query(OptimizationSession)
                .filter(OptimizationSession.session_id == session_id)
                .first()
            )
            if not session:
                raise ValueError(f"Unknown optimization session: {session_id}")

            event_key = StreamManager._event_key(data)
            event = TaskEvent(
                session_id=session.id,
                event_type=str(data.get("type") or "message")[:64],
                event_key=event_key,
                payload_json=json.dumps(data, ensure_ascii=False, default=str),
            )
            db.add(event)
            db.flush()

            # Content payloads contain a full_text snapshot. Keep only the most
            # recent snapshot for the same segment/stage to bound replay size.
            if event_key:
                (
                    db.query(TaskEvent)
                    .filter(
                        TaskEvent.session_id == session.id,
                        TaskEvent.event_key == event_key,
                        TaskEvent.id < event.id,
                    )
                    .delete(synchronize_session=False)
                )

            db.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": TASK_EVENT_CHANNEL, "payload": str(event.id)},
            )
            db.commit()
            return int(event.id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def broadcast(self, session_id: str, data: Dict[str, Any]) -> int:
        """Persist an event before waking local and remote SSE consumers."""
        event_id = await asyncio.to_thread(self._persist_event, session_id, data)
        await self._wake_connections(event_id)
        return event_id

    async def _wake_connections(self, event_id: int) -> None:
        async with self._lock:
            queues = [queue for values in self.connections.values() for queue in values]

        for queue in queues:
            try:
                queue.put_nowait(event_id)
            except asyncio.QueueFull:
                # A wake-up can be dropped safely: every SSE loop polls the
                # durable outbox and advances by event ID.
                continue

    @staticmethod
    def fetch_events(session_db_id: int, after_id: int, limit: int = 200) -> list[TaskEvent]:
        db = SessionLocal()
        try:
            events = (
                db.query(TaskEvent)
                .filter(
                    TaskEvent.session_id == session_db_id,
                    TaskEvent.id > max(0, after_id),
                )
                .order_by(TaskEvent.id.asc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            for event in events:
                db.expunge(event)
            return events
        finally:
            db.close()


stream_manager = StreamManager()
