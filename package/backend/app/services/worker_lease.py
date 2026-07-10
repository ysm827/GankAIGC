from app.database import SessionLocal
from app.models.models import WorkerLease
from app.utils.time import utcnow


def register_worker_lease(
    worker_id: str,
    boot_id: str,
    *,
    version: str | None,
    capacity: int = 1,
) -> None:
    now = utcnow()
    db = SessionLocal()
    try:
        lease = db.get(WorkerLease, worker_id)
        if not lease:
            lease = WorkerLease(worker_id=worker_id, boot_id=boot_id)
            db.add(lease)
        lease.boot_id = boot_id
        lease.version = version
        lease.state = "idle"
        lease.capacity = max(1, capacity)
        lease.current_session_id = None
        lease.started_at = now
        lease.last_seen_at = now
        lease.updated_at = now
        db.commit()
    finally:
        db.close()


def update_worker_lease(
    worker_id: str,
    boot_id: str,
    *,
    state: str,
    current_session_id: int | None = None,
) -> bool:
    db = SessionLocal()
    try:
        lease = (
            db.query(WorkerLease)
            .filter(
                WorkerLease.worker_id == worker_id,
                WorkerLease.boot_id == boot_id,
            )
            .first()
        )
        if not lease:
            return False
        now = utcnow()
        lease.state = state
        lease.current_session_id = current_session_id
        lease.last_seen_at = now
        lease.updated_at = now
        db.commit()
        return True
    finally:
        db.close()


def stop_worker_lease(worker_id: str, boot_id: str) -> bool:
    return update_worker_lease(
        worker_id,
        boot_id,
        state="stopped",
        current_session_id=None,
    )
