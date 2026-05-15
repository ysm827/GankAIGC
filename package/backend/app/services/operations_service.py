import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

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
from app.utils.url_security import validate_model_base_url


BACKUP_NAME_PREFIX = "gankaigc_"
BACKUP_NAME_SUFFIX = ".dump"


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


def get_backup_dir() -> Path:
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


def get_database_status() -> Dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "message": "数据库连接正常"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_worker_status(db: Session) -> Dict[str, Any]:
    processing_count = db.query(OptimizationSession).filter(OptimizationSession.status == "processing").count() or 0
    queued_count = db.query(OptimizationSession).filter(OptimizationSession.status == "queued").count() or 0
    failed_count = db.query(OptimizationSession).filter(OptimizationSession.status == "failed").count() or 0
    latest_processing = (
        db.query(OptimizationSession)
        .filter(OptimizationSession.status == "processing")
        .order_by(OptimizationSession.updated_at.desc().nullslast(), OptimizationSession.started_at.desc().nullslast())
        .first()
    )

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

    return {
        "ok": likely_running,
        "mode": "inline" if inline_enabled else "docker-worker",
        "inline_worker_enabled": inline_enabled,
        "processing_count": processing_count,
        "queued_count": queued_count,
        "failed_count": failed_count,
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


def get_onboarding_status(db: Session, backup_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    backup_status = backup_status or get_backup_status()
    has_invite = db.query(RegistrationInvite).count() > 0
    has_completed_task = (
        db.query(OptimizationSession)
        .filter(OptimizationSession.status == "completed")
        .count()
        > 0
    )

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
            "hint": "在用户管理里创建邀请码，确认新用户能注册。",
        },
        {
            "key": "test_task",
            "title": "完成一次测试处理",
            "done": has_completed_task,
            "hint": "用普通用户提交一小段文本，确认处理链路能跑通。",
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
    can_run_update, disabled_reason = update_service.can_run_vps_update()
    git_status = update_service.get_git_revision_status()
    backup_status = get_backup_status()
    return {
        "app": {
            "version": update_service.get_current_app_version(),
            "environment": settings.APP_ENV,
            "env_file": get_env_file_path(),
            "backup_dir": str(get_backup_dir()),
        },
        "database": get_database_status(),
        "worker": get_worker_status(db),
        "backup": backup_status,
        "onboarding": get_onboarding_status(db, backup_status),
        "update": {
            "enabled": settings.VPS_UPDATE_ENABLED,
            "can_run": can_run_update,
            "disabled_reason": disabled_reason,
            "workdir": settings.VPS_UPDATE_WORKDIR,
            "docker_socket_mounted": os.path.exists("/var/run/docker.sock"),
            "host_project_dir": os.environ.get("GANKAIGC_HOST_PROJECT_DIR"),
            "source_update_available": git_status.get("source_update_available"),
            "git_error": git_status.get("error"),
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


def get_model_config(stage: str) -> Dict[str, str]:
    stage_map = {
        "polish": {
            "label": "润色模型",
            "model": settings.POLISH_MODEL,
            "api_key": settings.POLISH_API_KEY or settings.OPENAI_API_KEY,
            "base_url": settings.POLISH_BASE_URL or settings.OPENAI_BASE_URL,
        },
        "enhance": {
            "label": "增强模型",
            "model": settings.ENHANCE_MODEL,
            "api_key": settings.ENHANCE_API_KEY or settings.OPENAI_API_KEY,
            "base_url": settings.ENHANCE_BASE_URL or settings.OPENAI_BASE_URL,
        },
        "emotion": {
            "label": "感情润色模型",
            "model": settings.EMOTION_MODEL or settings.POLISH_MODEL,
            "api_key": settings.EMOTION_API_KEY or settings.POLISH_API_KEY or settings.OPENAI_API_KEY,
            "base_url": settings.EMOTION_BASE_URL or settings.POLISH_BASE_URL or settings.OPENAI_BASE_URL,
        },
        "compression": {
            "label": "压缩模型",
            "model": settings.COMPRESSION_MODEL,
            "api_key": settings.COMPRESSION_API_KEY or settings.OPENAI_API_KEY,
            "base_url": settings.COMPRESSION_BASE_URL or settings.OPENAI_BASE_URL,
        },
    }
    if stage not in stage_map:
        raise ValueError("不支持的模型测试类型")
    config = stage_map[stage]
    return {
        "stage": stage,
        "label": config["label"],
        "model": _normalize_model(config["model"]),
        "api_key": _normalize_api_key(config["api_key"]),
        "base_url": _normalize_base_url(config["base_url"]),
    }


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
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时，请检查 Base URL 或网络"
    return str(exc)


async def test_model_connection(stage: str) -> Dict[str, Any]:
    try:
        config = get_model_config(stage)
    except ValueError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": "",
            "model": None,
            "base_url": None,
            "message": str(exc),
        }

    try:
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
            "message": _classify_model_test_error(exc),
        }


async def test_provider_model_connection(provider_config: Dict[str, Optional[str]]) -> Dict[str, Any]:
    stage = "provider"
    label = "自带 API"
    try:
        model = _normalize_model(provider_config.get("polish_model") or provider_config.get("enhance_model"))
        api_key = _normalize_api_key(provider_config.get("api_key"))
        base_url = _normalize_base_url(provider_config.get("base_url"))
    except ValueError as exc:
        return {
            "ok": False,
            "stage": stage,
            "label": label,
            "model": None,
            "base_url": None,
            "message": str(exc),
        }

    try:
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
            "message": _classify_model_test_error(exc),
        }
