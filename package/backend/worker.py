import asyncio
import contextlib
import os
import signal
import socket
import uuid

from app.config import reload_settings, settings
from app.schema import prepare_database
from app.services.task_queue import process_next_queued_session
from app.services.worker_lease import (
    register_worker_lease,
    stop_worker_lease,
    update_worker_lease,
)


async def worker_loop() -> None:
    worker_id = (
        os.environ.get("TASK_WORKER_ID")
        or f"{socket.gethostname()}-{os.getpid()}"
    )[:128]
    boot_id = uuid.uuid4().hex
    shutdown_requested = asyncio.Event()
    runtime = {"state": "idle", "session_id": None}

    register_worker_lease(
        worker_id,
        boot_id,
        version=settings.APP_VERSION,
        capacity=1,
    )
    print(f"GankAIGC worker started: {worker_id} boot={boot_id}", flush=True)

    def request_shutdown() -> None:
        runtime["state"] = "draining"
        shutdown_requested.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, request_shutdown)

    async def lease_heartbeat() -> None:
        while True:
            interval = min(
                max(1.0, float(settings.TASK_WORKER_HEARTBEAT_INTERVAL or 1)),
                max(1.0, float(settings.TASK_WORKER_LEASE_TIMEOUT_SECONDS) / 3),
            )
            await asyncio.sleep(interval)
            update_worker_lease(
                worker_id,
                boot_id,
                state=str(runtime["state"]),
                current_session_id=runtime["session_id"],
            )

    heartbeat_task = asyncio.create_task(lease_heartbeat())
    try:
        while not shutdown_requested.is_set():
            try:
                reload_settings()
            except Exception as exc:
                print(
                    f"[WARN] Worker reload settings failed, keep previous config: {exc}",
                    flush=True,
                )

            runtime["state"] = "idle"
            runtime["session_id"] = None
            update_worker_lease(worker_id, boot_id, state="idle")

            def on_claimed(session) -> None:
                runtime["state"] = "draining" if shutdown_requested.is_set() else "busy"
                runtime["session_id"] = session.id
                update_worker_lease(
                    worker_id,
                    boot_id,
                    state=str(runtime["state"]),
                    current_session_id=session.id,
                )

            processed = await process_next_queued_session(
                worker_id,
                on_claimed=on_claimed,
            )
            runtime["session_id"] = None
            if shutdown_requested.is_set():
                break
            runtime["state"] = "idle"
            update_worker_lease(worker_id, boot_id, state="idle")

            if not processed:
                try:
                    await asyncio.wait_for(
                        shutdown_requested.wait(),
                        timeout=max(0.1, settings.TASK_WORKER_POLL_INTERVAL),
                    )
                except asyncio.TimeoutError:
                    pass
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        stop_worker_lease(worker_id, boot_id)
        print(f"GankAIGC worker stopped: {worker_id} boot={boot_id}", flush=True)


def main() -> None:
    prepare_database()
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
