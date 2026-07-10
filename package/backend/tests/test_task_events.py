import asyncio
import json

from app.database import SessionLocal
from app.models.models import OptimizationSession, User
from app.services.stream_manager import StreamManager, stream_manager
from app.utils.auth import get_password_hash


def _create_session(session_id: str) -> int:
    db = SessionLocal()
    try:
        user = User(
            username=f"user-{session_id}",
            password_hash=get_password_hash("Password123!"),
            access_link=f"http://testserver/access/{session_id}",
            is_active=True,
        )
        db.add(user)
        db.flush()
        session = OptimizationSession(
            user_id=user.id,
            session_id=session_id,
            original_text="测试正文",
            current_stage="polish",
            status="processing",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session.id
    finally:
        db.close()


def test_task_events_are_replayable_by_monotonic_event_id():
    session_db_id = _create_session("event-replay")

    first_id = asyncio.run(
        stream_manager.broadcast("event-replay", {"type": "status", "status": "processing"})
    )
    second_id = asyncio.run(
        stream_manager.broadcast("event-replay", {"type": "status", "status": "completed"})
    )

    assert second_id > first_id
    replay = stream_manager.fetch_events(session_db_id, first_id)
    assert [event.id for event in replay] == [second_id]
    assert json.loads(replay[0].payload_json)["status"] == "completed"


def test_content_events_keep_latest_full_text_snapshot_for_reconnect():
    session_db_id = _create_session("content-replay")

    first_id = asyncio.run(
        stream_manager.broadcast(
            "content-replay",
            {
                "type": "content",
                "segment_index": 0,
                "stage": "polish",
                "content": "前",
                "full_text": "前",
            },
        )
    )
    second_id = asyncio.run(
        stream_manager.broadcast(
            "content-replay",
            {
                "type": "content",
                "segment_index": 0,
                "stage": "polish",
                "content": "后",
                "full_text": "前后",
            },
        )
    )

    replay = stream_manager.fetch_events(session_db_id, 0)
    assert second_id > first_id
    assert [event.id for event in replay] == [second_id]
    assert json.loads(replay[0].payload_json)["full_text"] == "前后"


def test_local_wakeup_is_only_a_hint_and_durable_fetch_is_source_of_truth():
    session_db_id = _create_session("event-wakeup")

    async def scenario():
        queue = await stream_manager.connect("event-wakeup")
        try:
            event_id = await stream_manager.broadcast(
                "event-wakeup",
                {"type": "status", "status": "processing"},
            )
            wake_id = await asyncio.wait_for(queue.get(), timeout=2)
            return event_id, wake_id
        finally:
            await stream_manager.disconnect("event-wakeup", queue)
            await stream_manager.close()

    event_id, wake_id = asyncio.run(scenario())
    assert wake_id == event_id
    assert [event.id for event in stream_manager.fetch_events(session_db_id, 0)] == [event_id]


def test_postgres_notify_wakes_a_separate_stream_manager_instance():
    _create_session("cross-process-wakeup")
    listener = StreamManager()
    publisher = StreamManager()

    async def scenario():
        queue = await listener.connect("cross-process-wakeup")
        try:
            await asyncio.sleep(0.1)
            event_id = await publisher.broadcast(
                "cross-process-wakeup",
                {"type": "status", "status": "processing"},
            )
            wake_id = await asyncio.wait_for(queue.get(), timeout=3)
            return event_id, wake_id
        finally:
            await listener.disconnect("cross-process-wakeup", queue)
            await listener.close()
            await publisher.close()

    event_id, wake_id = asyncio.run(scenario())
    assert wake_id == event_id
