import os
import platform
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, AsyncOpenAI, NotFoundError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import (
    get_env_file_path,
    get_exe_dir,
    is_placeholder_admin_password,
    is_placeholder_secret,
    settings,
)
from app.database import engine
from app.models.models import OptimizationSession, RegistrationInvite
from app.services import update_service
from app.services.ai_service import (
    ANTHROPIC_MODEL_IDS,
    API_FORMAT_ANTHROPIC,
    API_FORMAT_OPENAI_CHAT,
    anthropic_headers,
    anthropic_messages_url,
    build_anthropic_messages_payload,
    normalize_api_format,
)
from app.utils.url_security import validate_model_base_url


BACKUP_NAME_PREFIX = "gankaigc_"
BACKUP_NAME_SUFFIX = ".dump"
MODEL_STAGE_DEFINITIONS = {
    "polish": {
        "label": "润色模型",
        "model_attr": "POLISH_MODEL",
        "api_key_attrs": ("POLISH_API_KEY", "OPENAI_API_KEY"),
        "base_url_attrs": ("POLISH_BASE_URL", "OPENAI_BASE_URL"),
        "api_format_attrs": ("MODEL_API_FORMAT",),
    },
    "enhance": {
        "label": "增强模型",
        "model_attr": "ENHANCE_MODEL",
        "api_key_attrs": ("ENHANCE_API_KEY", "OPENAI_API_KEY"),
        "base_url_attrs": ("ENHANCE_BASE_URL", "OPENAI_BASE_URL"),
        "api_format_attrs": ("MODEL_API_FORMAT",),
    },
    "emotion": {
        "label": "感情润色模型",
        "model_attr": "EMOTION_MODEL",
        "fallback_model_attrs": ("POLISH_MODEL",),
        "api_key_attrs": ("EMOTION_API_KEY", "POLISH_API_KEY", "OPENAI_API_KEY"),
        "base_url_attrs": ("EMOTION_BASE_URL", "POLISH_BASE_URL", "OPENAI_BASE_URL"),
        "api_format_attrs": ("MODEL_API_FORMAT",),
    },
    "compression": {
        "label": "压缩模型",
        "model_attr": "COMPRESSION_MODEL",
        "api_key_attrs": ("COMPRESSION_API_KEY", "OPENAI_API_KEY"),
        "base_url_attrs": ("COMPRESSION_BASE_URL", "OPENAI_BASE_URL"),
        "api_format_attrs": ("MODEL_API_FORMAT",),
    },
}
PLACEHOLDER_API_KEYS = {"pwd", "replace-me", "please-change-this-api-key"}
PLACEHOLDER_BASE_URL_MARKERS = ("ip:port", "localhost:port", "example.com")
_CPU_SNAPSHOT: Optional[Tuple[float, int, int]] = None
_NETWORK_SNAPSHOT: Optional[Tuple[float, int, int]] = None


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(max(size, 0))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _format_rate(bytes_per_second: Optional[float]) -> str:
    if bytes_per_second is None:
        return "不可用"
    return f"{_format_bytes(int(max(bytes_per_second, 0)))}/s"


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "不可用"
    total_seconds = max(0, int(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}天 {hours}小时"
    if hours:
        return f"{hours}小时 {minutes}分钟"
    return f"{minutes}分钟"


def _round_float(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _read_proc_uptime() -> Optional[float]:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except Exception:
        return None


def _read_proc_cpu_times() -> Optional[Tuple[int, int]]:
    try:
        first_line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        parts = [int(value) for value in first_line.split()[1:]]
        if len(parts) < 4:
            return None
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        total = sum(parts)
        return total, idle
    except Exception:
        return None


def _get_physical_cpu_count() -> Optional[int]:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return None
    try:
        physical_pairs = set()
        current_physical_id = "0"
        current_core_id = None
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                if current_core_id is not None:
                    physical_pairs.add((current_physical_id, current_core_id))
                current_physical_id = "0"
                current_core_id = None
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "physical id":
                current_physical_id = value
            elif key == "core id":
                current_core_id = value
        if current_core_id is not None:
            physical_pairs.add((current_physical_id, current_core_id))
        return len(physical_pairs) or None
    except Exception:
        return None


def _calculate_cpu_percent() -> Optional[float]:
    global _CPU_SNAPSHOT
    current = _read_proc_cpu_times()
    if current is None:
        return None

    now = time.monotonic()
    total, idle = current
    previous = _CPU_SNAPSHOT
    _CPU_SNAPSHOT = (now, total, idle)

    if previous:
        _, previous_total, previous_idle = previous
        total_delta = total - previous_total
        idle_delta = idle - previous_idle
        if total_delta > 0:
            return max(0.0, min(100.0, (1.0 - (idle_delta / total_delta)) * 100.0))

    # First request after process start: take a tiny real sample instead of inventing a placeholder.
    time.sleep(0.05)
    sampled = _read_proc_cpu_times()
    sampled_at = time.monotonic()
    if sampled is None:
        return None
    sampled_total, sampled_idle = sampled
    _CPU_SNAPSHOT = (sampled_at, sampled_total, sampled_idle)
    total_delta = sampled_total - total
    idle_delta = sampled_idle - idle
    if total_delta <= 0:
        return None
    return max(0.0, min(100.0, (1.0 - (idle_delta / total_delta)) * 100.0))


def _read_proc_meminfo() -> Dict[str, int]:
    result: Dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw_value = line.partition(":")
            value_parts = raw_value.strip().split()
            if value_parts:
                result[key] = int(value_parts[0]) * 1024
    except Exception:
        return {}
    return result


def _read_network_totals() -> Optional[Tuple[int, int]]:
    net_file = Path("/proc/net/dev")
    if not net_file.exists():
        return None
    rx_total = 0
    tx_total = 0
    try:
        for line in net_file.read_text(encoding="utf-8").splitlines()[2:]:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            parts = data.split()
            if len(parts) < 16:
                continue
            rx_total += int(parts[0])
            tx_total += int(parts[8])
    except Exception:
        return None
    return rx_total, tx_total


def _calculate_network_status() -> Dict[str, Any]:
    global _NETWORK_SNAPSHOT
    current = _read_network_totals()
    if current is None:
        return {
            "available": False,
            "rx_rate_bps": None,
            "tx_rate_bps": None,
            "rx_rate_label": "不可用",
            "tx_rate_label": "不可用",
            "message": "当前平台无法读取网络接口计数",
        }

    now = time.monotonic()
    rx_total, tx_total = current
    previous = _NETWORK_SNAPSHOT
    _NETWORK_SNAPSHOT = (now, rx_total, tx_total)

    if previous:
        previous_at, previous_rx, previous_tx = previous
        elapsed = max(now - previous_at, 0.001)
        rx_rate = max(0.0, (rx_total - previous_rx) / elapsed)
        tx_rate = max(0.0, (tx_total - previous_tx) / elapsed)
    else:
        time.sleep(0.05)
        sampled = _read_network_totals()
        sampled_at = time.monotonic()
        if sampled is None:
            rx_rate = None
            tx_rate = None
        else:
            sampled_rx, sampled_tx = sampled
            _NETWORK_SNAPSHOT = (sampled_at, sampled_rx, sampled_tx)
            elapsed = max(sampled_at - now, 0.001)
            rx_rate = max(0.0, (sampled_rx - rx_total) / elapsed)
            tx_rate = max(0.0, (sampled_tx - tx_total) / elapsed)

    return {
        "available": True,
        "rx_bytes": rx_total,
        "tx_bytes": tx_total,
        "rx_rate_bps": _round_float(rx_rate, 2),
        "tx_rate_bps": _round_float(tx_rate, 2),
        "rx_rate_label": _format_rate(rx_rate),
        "tx_rate_label": _format_rate(tx_rate),
        "message": "网络接口计数已读取",
    }


def get_system_status(database_ok: bool, backup_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    logical_cpus = os.cpu_count() or 1
    physical_cpus = _get_physical_cpu_count()
    cpu_percent = _calculate_cpu_percent()
    meminfo = _read_proc_meminfo()
    mem_total = meminfo.get("MemTotal")
    mem_available = meminfo.get("MemAvailable")
    mem_used = mem_total - mem_available if mem_total is not None and mem_available is not None else None
    mem_percent = (mem_used / mem_total * 100.0) if mem_total else None

    disk_path = Path(get_exe_dir())
    if not disk_path.exists():
        disk_path = Path.cwd()
    disk_usage = shutil.disk_usage(disk_path)
    disk_percent = disk_usage.used / disk_usage.total * 100.0 if disk_usage.total else None
    load_available = hasattr(os, "getloadavg")
    if load_available:
        load1, load5, load15 = os.getloadavg()
    else:
        load1 = load5 = load15 = None

    network = _calculate_network_status()
    backup_count = (backup_status or {}).get("total_files", 0)
    cpu_ok = cpu_percent is None or cpu_percent < 90.0
    memory_ok = mem_percent is None or mem_percent < 90.0
    disk_ok = disk_percent is None or disk_percent < 90.0
    load_ok = load1 is None or load1 < logical_cpus * 1.5

    return {
        "ok": bool(database_ok and cpu_ok and memory_ok and disk_ok and load_ok),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "uptime_seconds": _round_float(_read_proc_uptime(), 0),
        "uptime_label": _format_duration(_read_proc_uptime()),
        "cpu": {
            "available": cpu_percent is not None,
            "ok": cpu_ok,
            "percent": _round_float(cpu_percent, 1),
            "physical_cores": physical_cpus,
            "logical_cpus": logical_cpus,
        },
        "memory": {
            "available": mem_total is not None,
            "ok": memory_ok,
            "total_bytes": mem_total,
            "used_bytes": mem_used,
            "available_bytes": mem_available,
            "percent": _round_float(mem_percent, 1),
            "used_label": _format_bytes(mem_used or 0) if mem_used is not None else "不可用",
            "total_label": _format_bytes(mem_total or 0) if mem_total is not None else "不可用",
        },
        "disk": {
            "available": True,
            "ok": disk_ok,
            "path": str(disk_path),
            "total_bytes": disk_usage.total,
            "used_bytes": disk_usage.used,
            "free_bytes": disk_usage.free,
            "percent": _round_float(disk_percent, 1),
            "used_label": _format_bytes(disk_usage.used),
            "total_label": _format_bytes(disk_usage.total),
            "backup_file_count": backup_count,
        },
        "network": network,
        "load": {
            "available": load_available,
            "ok": load_ok,
            "load1": _round_float(load1, 2),
            "load5": _round_float(load5, 2),
            "load15": _round_float(load15, 2),
            "logical_cpus": logical_cpus,
        },
    }


def get_backup_dir() -> Path:
    docker_backup_dir = Path("/backups")
    if docker_backup_dir.exists() and docker_backup_dir.is_dir():
        return docker_backup_dir

    configured = Path(settings.BACKUP_DIR)
    if configured.is_absolute():
        return configured

    update_workdir = Path(settings.VPS_UPDATE_WORKDIR)
    if update_workdir.exists() and update_workdir.is_dir():
        return update_workdir / configured

    host_project_dir = os.environ.get("GANKAIGC_HOST_PROJECT_DIR")
    if host_project_dir and Path(host_project_dir).exists():
        return Path(host_project_dir) / configured

    return Path(get_exe_dir()) / configured


def _iter_backup_files(backup_dir: Path) -> Iterable[Path]:
    if not backup_dir.exists() or not backup_dir.is_dir():
        return []
    return backup_dir.glob(f"{BACKUP_NAME_PREFIX}*{BACKUP_NAME_SUFFIX}")


def _serialize_backup_file(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return {
        "filename": path.name,
        "size_bytes": stat.st_size,
        "size_label": _format_bytes(stat.st_size),
        "modified_at": modified_at.isoformat(),
    }


def get_backup_status(limit: int = 8) -> Dict[str, Any]:
    backup_dir = get_backup_dir()
    files = sorted(
        (_serialize_backup_file(path) for path in _iter_backup_files(backup_dir)),
        key=lambda item: item["modified_at"],
        reverse=True,
    )
    latest = files[0] if files else None
    exists = backup_dir.exists() and backup_dir.is_dir()
    return {
        "enabled": exists,
        "directory": str(backup_dir),
        "retention_days": settings.BACKUP_RETENTION_DAYS,
        "interval_seconds": settings.BACKUP_INTERVAL_SECONDS,
        "total_files": len(files),
        "latest": latest,
        "files": files[:limit],
        "message": None if exists else "未检测到备份目录。Docker 部署会默认挂载宿主机 backups/ 目录。",
    }


def resolve_backup_file(filename: str) -> Path:
    if not filename or filename != os.path.basename(filename):
        raise ValueError("备份文件名不合法")
    if not filename.startswith(BACKUP_NAME_PREFIX) or not filename.endswith(BACKUP_NAME_SUFFIX):
        raise ValueError("只允许下载 GankAIGC PostgreSQL 备份文件")

    backup_dir = get_backup_dir().resolve()
    target = (backup_dir / filename).resolve()
    if backup_dir not in target.parents and target != backup_dir:
        raise ValueError("备份文件路径不合法")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("备份文件不存在")
    return target


def _get_slow_query_count(conn) -> Optional[int]:
    try:
        result = conn.execute(
            text(
                """
                SELECT count(*)
                FROM pg_stat_activity
                WHERE state = 'active'
                  AND pid <> pg_backend_pid()
                  AND query_start IS NOT NULL
                  AND now() - query_start > interval '1 second'
                """
            )
        )
        return int(result.scalar() or 0)
    except Exception:
        return None


def get_database_status(sample_count: int = 5) -> Dict[str, Any]:
    try:
        with engine.connect() as conn:
            samples = []
            for _ in range(max(1, sample_count)):
                started = time.perf_counter()
                conn.execute(text("SELECT 1"))
                samples.append(round((time.perf_counter() - started) * 1000, 2))
            slow_query_count = _get_slow_query_count(conn)
        average_latency = sum(samples) / len(samples)
        return {
            "ok": True,
            "message": "数据库连接正常",
            "average_latency_ms": round(average_latency, 2),
            "latency_samples_ms": samples,
            "slow_query_count": slow_query_count,
        }
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "ok": False,
            "message": str(exc),
            "average_latency_ms": None,
            "latency_samples_ms": [],
            "slow_query_count": None,
        }


def get_worker_status(db: Session) -> Dict[str, Any]:
    try:
        processing_count = db.query(OptimizationSession).filter(OptimizationSession.status == "processing").count() or 0
        queued_count = db.query(OptimizationSession).filter(OptimizationSession.status == "queued").count() or 0
        failed_count = db.query(OptimizationSession).filter(OptimizationSession.status == "failed").count() or 0
        latest_processing = (
            db.query(OptimizationSession)
            .filter(OptimizationSession.status == "processing")
            .order_by(OptimizationSession.updated_at.desc().nullslast(), OptimizationSession.started_at.desc().nullslast())
            .first()
        )
    except Exception as exc:
        return {
            "ok": False,
            "mode": "inline" if settings.INLINE_TASK_WORKER_ENABLED else "docker-worker",
            "inline_worker_enabled": settings.INLINE_TASK_WORKER_ENABLED,
            "processing_count": 0,
            "queued_count": 0,
            "failed_count": 0,
            "capacity": max(1, int(settings.MAX_CONCURRENT_USERS or 1)) if settings.INLINE_TASK_WORKER_ENABLED else 1,
            "available_slots": 0,
            "unavailable_count": 1,
            "worker_count": 0,
            "last_worker_id": None,
            "last_heartbeat_at": None,
            "heartbeat_age_seconds": None,
            "message": f"无法读取任务队列状态：{exc}",
        }

    last_heartbeat = latest_processing.updated_at if latest_processing else None
    stale_seconds = None
    if last_heartbeat:
        heartbeat = last_heartbeat
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        stale_seconds = max(0, int((datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()))

    inline_enabled = settings.INLINE_TASK_WORKER_ENABLED
    likely_running = inline_enabled or processing_count > 0
    if processing_count > 0 and stale_seconds is not None:
        likely_running = stale_seconds <= settings.TASK_WORKER_STALE_TIMEOUT_SECONDS

    capacity = max(1, int(settings.MAX_CONCURRENT_USERS or 1)) if inline_enabled else 1
    available_slots = max(0, capacity - processing_count) if likely_running else 0
    unavailable_count = 0 if likely_running else 1

    return {
        "ok": likely_running,
        "mode": "inline" if inline_enabled else "docker-worker",
        "inline_worker_enabled": inline_enabled,
        "processing_count": processing_count,
        "queued_count": queued_count,
        "failed_count": failed_count,
        "capacity": capacity,
        "available_slots": available_slots,
        "unavailable_count": unavailable_count,
        "worker_count": 1 if likely_running else 0,
        "last_worker_id": latest_processing.worker_id if latest_processing else None,
        "last_heartbeat_at": _utc_iso(last_heartbeat),
        "heartbeat_age_seconds": stale_seconds,
        "message": "inline worker 已启用" if inline_enabled else "独立 worker 模式，按任务心跳判断运行状态",
    }


def _has_model_api_configured() -> bool:
    model = (settings.POLISH_MODEL or settings.OPENAI_API_KEY or "").strip()
    api_key = (settings.POLISH_API_KEY or settings.OPENAI_API_KEY or "").strip()
    base_url = (settings.POLISH_BASE_URL or settings.OPENAI_BASE_URL or "").strip()
    normalized_api_key = api_key.lower()
    normalized_base_url = base_url.lower()
    if normalized_api_key in {"pwd", "replace-me", "please-change-this-api-key"}:
        return False
    if any(marker in normalized_base_url for marker in ("ip:port", "localhost:port", "example.com")):
        return False
    return bool(model and api_key and base_url and base_url.startswith(("http://", "https://")))


def _first_setting_value(names: Iterable[str]) -> Optional[str]:
    for name in names:
        value = getattr(settings, name, None)
        if value:
            return str(value)
    return None


def _raw_model_stage_config(stage: str) -> Dict[str, Optional[str]]:
    definition = MODEL_STAGE_DEFINITIONS.get(stage)
    if not definition:
        raise ValueError("不支持的模型测试类型")

    model = getattr(settings, definition["model_attr"], None)
    if not model:
        model = _first_setting_value(definition.get("fallback_model_attrs", ()))
    api_key = _first_setting_value(definition["api_key_attrs"])
    base_url = _first_setting_value(definition["base_url_attrs"])
    api_format = _first_setting_value(definition.get("api_format_attrs", ())) or API_FORMAT_OPENAI_CHAT
    return {
        "stage": stage,
        "label": definition["label"],
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "api_format": normalize_api_format(api_format),
    }


def _is_placeholder_api_key(api_key: Optional[str]) -> bool:
    return (api_key or "").strip().lower() in PLACEHOLDER_API_KEYS


def _is_placeholder_base_url(base_url: Optional[str]) -> bool:
    normalized = (base_url or "").strip().lower()
    return any(marker in normalized for marker in PLACEHOLDER_BASE_URL_MARKERS)


def _redact_base_url(base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            return base_url
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return base_url


def get_model_readiness_status() -> Dict[str, Any]:
    items = []
    for stage in MODEL_STAGE_DEFINITIONS:
        raw = _raw_model_stage_config(stage)
        ok = True
        message = "已配置，点击系统配置里的「测试连接」可验证真实连通性"
        try:
            if _is_placeholder_api_key(raw.get("api_key")):
                raise ValueError("API Key 仍是占位值")
            if _is_placeholder_base_url(raw.get("base_url")):
                raise ValueError("Base URL 仍是占位值")
            config = get_model_config(stage)
            model = config["model"]
            base_url = config["base_url"]
            api_format = config["api_format"]
        except ValueError as exc:
            ok = False
            message = str(exc)
            model = raw.get("model")
            base_url = raw.get("base_url")
            api_format = normalize_api_format(raw.get("api_format"))
        items.append(
            {
                "stage": stage,
                "label": raw["label"],
                "model": model,
                "base_url": _redact_base_url(base_url),
                "api_format": api_format,
                "ok": ok,
                "message": message,
            }
        )
    return {
        "ok": all(item["ok"] for item in items),
        "items": items,
    }


def get_job_status(db: Session, backup_status: Dict[str, Any], worker_status: Dict[str, Any]) -> Dict[str, Any]:
    scheduled_count = sum(
        1
        for enabled in (
            settings.INLINE_TASK_WORKER_ENABLED,
            bool(backup_status.get("enabled")),
            settings.VPS_UPDATE_ENABLED,
        )
        if enabled
    )
    try:
        completed_count = db.query(OptimizationSession).filter(OptimizationSession.status == "completed").count() or 0
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        completed_count = None
    return {
        "scheduled_count": scheduled_count,
        "completed_count": completed_count,
        "processing_count": worker_status.get("processing_count", 0),
        "queued_count": worker_status.get("queued_count", 0),
        "failed_count": worker_status.get("failed_count", 0),
    }


def get_operations_events(
    db: Session,
    database_status: Dict[str, Any],
    worker_status: Dict[str, Any],
    backup_status: Dict[str, Any],
    limit: int = 6,
) -> list[Dict[str, Any]]:
    events: list[Dict[str, Any]] = []

    if backup_status.get("latest"):
        events.append(
            {
                "text": f"生成数据库备份 {backup_status['latest']['filename']}",
                "badge": "备份",
                "tone": "success",
                "timestamp": backup_status["latest"].get("modified_at"),
            }
        )

    if database_status.get("ok"):
        events.append(
            {
                "text": f"数据库连接正常，平均延迟 {database_status.get('average_latency_ms') or '--'} ms",
                "badge": "数据库",
                "tone": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    else:
        events.append(
            {
                "text": f"数据库异常：{database_status.get('message') or '连接失败'}",
                "badge": "异常",
                "tone": "warn",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    if worker_status.get("last_heartbeat_at"):
        events.append(
            {
                "text": f"Worker 心跳来自 {worker_status.get('last_worker_id') or worker_status.get('mode')}",
                "badge": "Worker",
                "tone": "info",
                "timestamp": worker_status.get("last_heartbeat_at"),
            }
        )

    try:
        recent_sessions = (
            db.query(OptimizationSession)
            .order_by(OptimizationSession.updated_at.desc().nullslast(), OptimizationSession.created_at.desc().nullslast())
            .limit(max(0, limit))
            .all()
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        recent_sessions = []
    status_badge_map = {
        "completed": ("任务完成", "success"),
        "failed": ("任务失败", "warn"),
        "processing": ("处理中", "info"),
        "queued": ("排队中", "info"),
        "stopped": ("已停止", "warn"),
    }
    for session in recent_sessions:
        badge, tone = status_badge_map.get(session.status, (session.status or "任务", "info"))
        events.append(
            {
                "text": f"会话 {session.session_id} · {session.current_stage or '未知阶段'}",
                "badge": badge,
                "tone": tone,
                "timestamp": _utc_iso(session.updated_at or session.created_at),
            }
        )

    def sort_key(item: Dict[str, Any]) -> str:
        return item.get("timestamp") or ""

    return sorted(events, key=sort_key, reverse=True)[:limit]


def get_onboarding_status(db: Session, backup_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    backup_status = backup_status or get_backup_status()
    try:
        has_invite = db.query(RegistrationInvite).count() > 0
        has_completed_task = (
            db.query(OptimizationSession)
            .filter(OptimizationSession.status == "completed")
            .count()
            > 0
        )
        database_readable = True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        has_invite = False
        has_completed_task = False
        database_readable = False

    items = [
        {
            "key": "admin_password",
            "title": "修改管理员密码",
            "done": not is_placeholder_admin_password(settings.ADMIN_PASSWORD),
            "hint": "在 .env.docker 或后台系统配置里把 ADMIN_PASSWORD 换成强密码。",
        },
        {
            "key": "secret_key",
            "title": "替换 JWT 密钥",
            "done": not is_placeholder_secret(settings.SECRET_KEY),
            "hint": "把 SECRET_KEY 换成随机长字符串，避免登录令牌可被伪造。",
        },
        {
            "key": "model_api",
            "title": "配置模型 API",
            "done": _has_model_api_configured(),
            "hint": "至少配置润色模型的 Model、API Key 和 Base URL，并在系统配置里测试连接。",
        },
        {
            "key": "invite",
            "title": "创建邀请码",
            "done": has_invite,
            "hint": "在用户管理里创建邀请码，确认新用户能注册。" if database_readable else "数据库不可读，暂时无法检查邀请码状态。",
        },
        {
            "key": "test_task",
            "title": "完成一次测试处理",
            "done": has_completed_task,
            "hint": "用普通用户提交一小段文本，确认处理链路能跑通。" if database_readable else "数据库不可读，暂时无法检查历史任务。",
        },
        {
            "key": "backup",
            "title": "确认自动备份",
            "done": bool(backup_status.get("enabled") and backup_status.get("total_files", 0) > 0),
            "hint": "后台运维状态里能看到最近备份文件，发布前建议手动下载验证一次。",
        },
    ]
    completed_count = sum(1 for item in items if item["done"])
    return {
        "ready": completed_count == len(items),
        "completed_count": completed_count,
        "total_count": len(items),
        "items": items,
    }


async def get_operations_status(db: Session) -> Dict[str, Any]:
    collected_at = datetime.now(timezone.utc).isoformat()
    can_run_update, disabled_reason = update_service.can_run_vps_update()
    backup_status = get_backup_status()
    database_status = get_database_status()
    worker_status = get_worker_status(db)
    system_status = get_system_status(bool(database_status.get("ok")), backup_status)
    return {
        "collected_at": collected_at,
        "app": {
            "version": update_service.get_current_app_version(),
            "environment": settings.APP_ENV,
            "env_file": get_env_file_path(),
            "backup_dir": str(get_backup_dir()),
        },
        "system": system_status,
        "database": database_status,
        "worker": worker_status,
        "models": get_model_readiness_status(),
        "jobs": get_job_status(db, backup_status, worker_status),
        "events": get_operations_events(db, database_status, worker_status, backup_status),
        "backup": backup_status,
        "onboarding": get_onboarding_status(db, backup_status),
        "update": {
            "enabled": settings.VPS_UPDATE_ENABLED,
            "mode": "manual_ssh",
            "can_run": can_run_update,
            "disabled_reason": disabled_reason,
        },
    }


def _normalize_base_url(base_url: Optional[str]) -> str:
    return validate_model_base_url(base_url or "")


def _normalize_api_key(api_key: Optional[str]) -> str:
    value = (api_key or "").strip()
    if not value:
        raise ValueError("API Key 未配置")
    return value


def _normalize_model(model: Optional[str]) -> str:
    value = (model or "").strip()
    if not value:
        raise ValueError("模型名称未配置")
    return value


def get_model_config(
    stage: str,
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_format: Optional[str] = None,
) -> Dict[str, str]:
    config = _raw_model_stage_config(stage)
    merged_model = model if (model or "").strip() else config.get("model")
    merged_api_key = api_key if (api_key or "").strip() else config.get("api_key")
    merged_base_url = base_url if (base_url or "").strip() else config.get("base_url")
    merged_api_format = api_format if (api_format or "").strip() else config.get("api_format")
    if _is_placeholder_api_key(merged_api_key):
        raise ValueError("API Key 仍是占位值")
    if _is_placeholder_base_url(merged_base_url):
        raise ValueError("Base URL 仍是占位值")
    return {
        "stage": stage,
        "label": config["label"],
        "model": _normalize_model(merged_model),
        "api_key": _normalize_api_key(merged_api_key),
        "base_url": _normalize_base_url(merged_base_url),
        "api_format": normalize_api_format(merged_api_format),
    }


def get_model_probe_config(
    stage: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_format: Optional[str] = None,
) -> Dict[str, str]:
    config = _raw_model_stage_config(stage)
    merged_api_key = api_key if (api_key or "").strip() else config.get("api_key")
    merged_base_url = base_url if (base_url or "").strip() else config.get("base_url")
    merged_api_format = api_format if (api_format or "").strip() else config.get("api_format")
    if _is_placeholder_api_key(merged_api_key):
        raise ValueError("API Key 仍是占位值")
    if _is_placeholder_base_url(merged_base_url):
        raise ValueError("Base URL 仍是占位值")
    return {
        "stage": stage,
        "label": config["label"],
        "api_key": _normalize_api_key(merged_api_key),
        "base_url": _normalize_base_url(merged_base_url),
        "api_format": normalize_api_format(merged_api_format),
    }


def _models_url_from_base_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _extract_model_ids(payload: Any) -> List[str]:
    raw_items: Any
    if isinstance(payload, dict):
        raw_items = payload.get("data")
        if raw_items is None:
            raw_items = payload.get("models")
    else:
        raw_items = payload

    if not isinstance(raw_items, list):
        raise ValueError("模型列表响应格式不正确")

    model_ids: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
        else:
            model_id = item
        if model_id is None:
            continue
        model_text = str(model_id).strip()
        if not model_text or model_text in seen:
            continue
        seen.add(model_text)
        model_ids.append(model_text)
    return model_ids


def _classify_model_test_error(exc: Exception) -> str:
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或权限不足"
    if isinstance(exc, NotFoundError):
        return "模型不存在或当前 Key 无权访问该模型"
    if isinstance(exc, APITimeoutError):
        return "请求超时，请检查 Base URL 或网络"
    if isinstance(exc, APIConnectionError):
        return "无法连接 API 服务，请检查 Base URL 或服务器网络"
    if isinstance(exc, APIStatusError):
        return f"API 服务返回错误 HTTP {exc.status_code}"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"API 服务返回错误 HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时，请检查 Base URL 或网络"
    return str(exc)


async def list_provider_models(
    stage: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_format: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        config = get_model_probe_config(stage, base_url=base_url, api_key=api_key, api_format=api_format)
    except ValueError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": "",
            "base_url": None,
            "api_format": API_FORMAT_OPENAI_CHAT,
            "models": [],
            "count": 0,
            "message": str(exc),
        }

    try:
        if config["api_format"] == API_FORMAT_ANTHROPIC:
            models = list(ANTHROPIC_MODEL_IDS)
            return {
                "ok": True,
                "stage": stage,
                "label": config["label"],
                "base_url": config["base_url"],
                "api_format": config["api_format"],
                "models": models,
                "count": len(models),
                "message": f"已载入 {len(models)} 个 Claude 模型",
            }

        async with httpx.AsyncClient(timeout=settings.MODEL_TEST_TIMEOUT_SECONDS) as client:
            response = await client.get(
                _models_url_from_base_url(config["base_url"]),
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
            response.raise_for_status()
            models = _extract_model_ids(response.json())
        return {
            "ok": True,
            "stage": stage,
            "label": config["label"],
            "base_url": config["base_url"],
            "api_format": config["api_format"],
            "models": models,
            "count": len(models),
            "message": f"已拉取 {len(models)} 个模型",
        }
    except httpx.HTTPStatusError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": config["label"],
            "base_url": config["base_url"],
            "api_format": config["api_format"],
            "models": [],
            "count": 0,
            "message": f"模型列表接口返回 HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": config["label"],
            "base_url": config["base_url"],
            "api_format": config["api_format"],
            "models": [],
            "count": 0,
            "message": _classify_model_test_error(exc),
        }


async def test_model_connection(
    stage: str,
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_format: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        config = get_model_config(stage, model=model, base_url=base_url, api_key=api_key, api_format=api_format)
    except ValueError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": "",
            "model": None,
            "base_url": None,
            "api_format": API_FORMAT_OPENAI_CHAT,
            "message": str(exc),
        }

    try:
        if config["api_format"] == API_FORMAT_ANTHROPIC:
            async with httpx.AsyncClient(timeout=settings.MODEL_TEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    anthropic_messages_url(config["base_url"]),
                    headers=anthropic_headers(config["api_key"]),
                    json=build_anthropic_messages_payload(
                        model=config["model"],
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=8,
                        temperature=0,
                    ),
                )
                response.raise_for_status()
                response_id = response.json().get("id")
        else:
            client = AsyncOpenAI(
                api_key=config["api_key"],
                base_url=config["base_url"],
                timeout=settings.MODEL_TEST_TIMEOUT_SECONDS,
                max_retries=0,
            )
            response = await client.chat.completions.create(
                model=config["model"],
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                temperature=0,
            )
            response_id = getattr(response, "id", None)
        return {
            "ok": True,
            "stage": stage,
            "label": config["label"],
            "model": config["model"],
            "base_url": config["base_url"],
            "api_format": config["api_format"],
            "message": "API 连接测试通过",
            "response_id": response_id,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": config["label"],
            "model": config["model"],
            "base_url": config["base_url"],
            "api_format": config["api_format"],
            "message": _classify_model_test_error(exc),
        }


async def test_provider_model_connection(provider_config: Dict[str, Optional[str]]) -> Dict[str, Any]:
    stage = "provider"
    label = "自带 API"
    try:
        model = _normalize_model(provider_config.get("polish_model") or provider_config.get("enhance_model"))
        api_key = _normalize_api_key(provider_config.get("api_key"))
        base_url = _normalize_base_url(provider_config.get("base_url"))
        api_format = normalize_api_format(provider_config.get("api_format"))
    except ValueError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": label,
            "model": None,
            "base_url": None,
            "api_format": API_FORMAT_OPENAI_CHAT,
            "message": str(exc),
        }

    try:
        if api_format == API_FORMAT_ANTHROPIC:
            async with httpx.AsyncClient(timeout=settings.MODEL_TEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    anthropic_messages_url(base_url),
                    headers=anthropic_headers(api_key),
                    json=build_anthropic_messages_payload(
                        model=model,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=8,
                        temperature=0,
                    ),
                )
                response.raise_for_status()
                response_id = response.json().get("id")
        else:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=settings.MODEL_TEST_TIMEOUT_SECONDS,
                max_retries=0,
            )
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
                temperature=0,
            )
            response_id = getattr(response, "id", None)
        return {
            "ok": True,
            "stage": stage,
            "label": label,
            "model": model,
            "base_url": base_url,
            "api_format": api_format,
            "message": "API 连接测试通过",
            "response_id": response_id,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": label,
            "model": model,
            "base_url": base_url,
            "api_format": api_format,
            "message": _classify_model_test_error(exc),
        }
