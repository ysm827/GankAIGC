import os
import json
import secrets
import csv
from io import StringIO
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Type

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect, func, case
from sqlalchemy.orm import Session, defer, joinedload

from app.config import reload_settings, settings
from app.database import get_db
from app.models.models import (
    AdminAuditLog,
    Announcement,
    ChangeLog,
    CreditCode,
    CreditTransaction,
    OptimizationSegment,
    OptimizationSession,
    RegistrationInvite,
    SessionHistory,
    SystemSetting,
    User,
    UserProviderConfig,
)
from app.runtime import refresh_cors_middleware
from app.schemas import (
    AdminCreditAdjustRequest,
    AnnouncementCreateRequest,
    AnnouncementResponse,
    AnnouncementUpdateRequest,
    CreditCodeBatchCreateRequest,
    CreditCodeCreateRequest,
    CreditCodeResponse,
    DatabaseUpdateRequest,
    InviteCreateRequest,
    UserResponse,
    UserUsageUpdate,
)
from app.services.concurrency import concurrency_manager
from app.services.credit_service import CreditService, serialize_credit_transaction
from app.services import operations_service, update_service
from app.utils.auth import (
    create_access_token,
    verify_token,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminLogin(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class ModelConnectionTestRequest(BaseModel):
    stage: str


def _session_user_identity(user: Optional[User]) -> Dict[str, Optional[str]]:
    if not user:
        return {
            "username": None,
            "nickname": None,
            "user_display_name": "未知用户",
        }

    return {
        "username": user.username,
        "nickname": user.nickname,
        "user_display_name": user.nickname or user.username or f"用户 #{user.id}",
    }


class UnlimitedToggleRequest(BaseModel):
    is_unlimited: bool


class InviteResponse(BaseModel):
    id: int
    code: str
    is_active: bool
    expires_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None
    created_by_nickname: Optional[str] = None
    created_by_display_name: Optional[str] = None
    created_by_type: str = "admin"
    used_by_user_id: Optional[int] = None
    used_by_username: Optional[str] = None
    used_by_nickname: Optional[str] = None
    used_by_display_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


ALLOWED_TABLES: Dict[str, Type] = {
    "users": User,
    "optimization_sessions": OptimizationSession,
    "optimization_segments": OptimizationSegment,
    "session_history": SessionHistory,
    "change_logs": ChangeLog,
    "system_settings": SystemSetting,
}

DATABASE_MANAGER_MAX_PAGE_SIZE = 100
DATABASE_MANAGER_MAX_TEXT_LENGTH = 240

SENSITIVE_DB_FIELDS = {
    "access_link",
    "password_hash",
    "api_key",
    "api_key_encrypted",
    "polish_api_key",
    "enhance_api_key",
    "emotion_api_key",
    "compression_api_key",
    "original_text",
    "polished_text",
    "enhanced_text",
    "before_text",
    "after_text",
    "changes_detail",
    "history_data",
    "error_message",
    "spec_json",
}
SENSITIVE_SYSTEM_SETTING_MARKERS = (
    "api_key",
    "password",
    "secret",
    "token",
    "encryption_key",
)


def verify_admin_credentials(username: str, password: str) -> bool:
    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD


def verify_admin_token(token: str) -> bool:
    payload = verify_token(token)
    if not payload:
        return False
    return payload.get("sub") == settings.ADMIN_USERNAME and payload.get("role") == "admin"


def get_admin_from_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证令牌")

    token = authorization.split(" ")[1]
    payload = verify_token(token)
    if not payload or payload.get("sub") != settings.ADMIN_USERNAME or payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    return str(payload.get("sub"))


def write_admin_audit_log(
    db: Session,
    admin_username: str,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> AdminAuditLog:
    log = AdminAuditLog(
        admin_username=admin_username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
    )
    db.add(log)
    return log


def serialize_admin_audit_log(log: AdminAuditLog) -> Dict[str, Any]:
    detail: Any = log.detail
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            pass
    return {
        "id": log.id,
        "admin_username": log.admin_username,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "detail": detail,
        "created_at": log.created_at,
    }


def _user_display_name(user: Optional[User], fallback_id: Optional[int] = None) -> Optional[str]:
    if user:
        return user.nickname or user.username or f"用户 #{user.id}"
    if fallback_id is not None:
        return f"用户 #{fallback_id}"
    return None


def serialize_registration_invite(invite: RegistrationInvite) -> Dict[str, Any]:
    creator = invite.created_by_user
    used_by = invite.used_by_user
    return {
        "id": invite.id,
        "code": invite.code,
        "is_active": invite.is_active,
        "expires_at": invite.expires_at,
        "created_by_user_id": invite.created_by_user_id,
        "created_by_username": creator.username if creator else None,
        "created_by_nickname": creator.nickname if creator else None,
        "created_by_display_name": _user_display_name(creator, invite.created_by_user_id),
        "created_by_type": "user" if invite.created_by_user_id else "admin",
        "used_by_user_id": invite.used_by_user_id,
        "used_by_username": used_by.username if used_by else None,
        "used_by_nickname": used_by.nickname if used_by else None,
        "used_by_display_name": _user_display_name(used_by, invite.used_by_user_id),
        "created_at": invite.created_at,
    }


def _generate_unique_credit_code(db: Session, reserved_codes: Optional[set[str]] = None) -> str:
    reserved_codes = reserved_codes or set()
    for _ in range(20):
        code = secrets.token_urlsafe(18)
        if code in reserved_codes:
            continue
        existing_code = db.query(CreditCode).filter(CreditCode.code == code).first()
        if not existing_code:
            return code
    raise HTTPException(status_code=500, detail="兑换码生成失败，请重试")


def _model_to_dict(record: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    mapper = inspect(record).mapper
    for column in mapper.columns:
        data[column.key] = getattr(record, column.key)
    return data


def sanitize_db_record(record: Dict[str, Any]) -> Dict[str, Any]:
    setting_key = str(record.get("key", "")).lower()
    sanitized: Dict[str, Any] = {}

    for key, value in record.items():
        normalized_key = key.lower()
        if normalized_key in SENSITIVE_DB_FIELDS:
            continue
        if normalized_key == "value" and any(marker in setting_key for marker in SENSITIVE_SYSTEM_SETTING_MARKERS):
            continue
        if isinstance(value, str) and len(value) > DATABASE_MANAGER_MAX_TEXT_LENGTH:
            sanitized[key] = f"{value[:DATABASE_MANAGER_MAX_TEXT_LENGTH]}..."
            continue
        sanitized[key] = value

    return sanitized


def _is_sensitive_system_setting_key(key: str) -> bool:
    normalized_key = key.lower()
    return any(marker in normalized_key for marker in SENSITIVE_SYSTEM_SETTING_MARKERS)


def _ensure_database_manager_enabled() -> None:
    if not settings.ADMIN_DATABASE_MANAGER_ENABLED:
        raise HTTPException(status_code=404, detail="数据库管理器已关闭")


def _ensure_database_write_enabled() -> None:
    _ensure_database_manager_enabled()
    if not settings.ADMIN_DATABASE_WRITE_ENABLED:
        raise HTTPException(status_code=403, detail="数据库管理器当前为只读模式")


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(credentials: AdminLogin) -> AdminLoginResponse:
    # 速率限制: 每分钟最多5次登录尝试 (在 main.py 的 limiter 中配置)
    if not verify_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": credentials.username, "role": "admin"},
        expires_delta=access_token_expires,
    )
    return AdminLoginResponse(access_token=access_token, username=credentials.username)


@router.post("/verify-token")
async def verify_admin_token_endpoint(authorization: Optional[str] = Header(None)) -> Dict[str, bool]:
    get_admin_from_token(authorization)
    return {"valid": True}


@router.get("/audit-logs")
async def list_admin_audit_logs(
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    logs = (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return [serialize_admin_audit_log(log) for log in logs]


@router.get("/update/status")
async def get_update_status(_: str = Depends(get_admin_from_token)) -> Dict[str, Any]:
    return await update_service.build_update_status()


@router.post("/update/run")
async def run_vps_update(
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    can_run_update, disabled_reason = update_service.can_run_vps_update()
    if not can_run_update:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=disabled_reason or "VPS 在线更新不可用",
        )

    try:
        result = update_service.start_vps_update()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_admin_audit_log(
        db,
        admin_username,
        "start_vps_update",
        target_type="system_update",
        detail={"message": result.get("message"), "command": result.get("command")},
    )
    db.commit()
    return result


@router.get("/operations/status")
async def get_operations_status(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await operations_service.get_operations_status(db)


@router.get("/operations/backups/{filename}/download")
async def download_backup_file(
    filename: str,
    _: str = Depends(get_admin_from_token),
) -> FileResponse:
    try:
        backup_file = operations_service.resolve_backup_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        backup_file,
        filename=backup_file.name,
        media_type="application/octet-stream",
    )


@router.post("/operations/model-test")
async def test_admin_model_connection(
    payload: ModelConnectionTestRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    result = await operations_service.test_model_connection(payload.stage)
    write_admin_audit_log(
        db,
        admin_username,
        "test_model_connection",
        target_type="system_config",
        detail={
            "stage": payload.stage,
            "ok": result.get("ok"),
            "model": result.get("model"),
            "base_url": result.get("base_url"),
            "message": result.get("message"),
        },
    )
    db.commit()
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.post("/invites", response_model=InviteResponse)
async def create_registration_invite(
    payload: InviteCreateRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    code = payload.code or secrets.token_urlsafe(18)
    existing_invite = db.query(RegistrationInvite).filter(RegistrationInvite.code == code).first()
    if existing_invite:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码已存在")

    invite = RegistrationInvite(code=code, is_active=True, expires_at=payload.expires_at)
    db.add(invite)
    db.flush()
    write_admin_audit_log(
        db,
        admin_username,
        "create_invite",
        target_type="registration_invite",
        target_id=invite.id,
        detail={"code": invite.code, "expires_at": invite.expires_at.isoformat() if invite.expires_at else None},
    )
    db.commit()
    invite = (
        db.query(RegistrationInvite)
        .options(joinedload(RegistrationInvite.created_by_user), joinedload(RegistrationInvite.used_by_user))
        .filter(RegistrationInvite.id == invite.id)
        .one()
    )
    return serialize_registration_invite(invite)


@router.get("/invites", response_model=List[InviteResponse])
async def list_registration_invites(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    invites = (
        db.query(RegistrationInvite)
        .options(joinedload(RegistrationInvite.created_by_user), joinedload(RegistrationInvite.used_by_user))
        .order_by(RegistrationInvite.created_at.desc())
        .all()
    )
    return [serialize_registration_invite(invite) for invite in invites]


@router.patch("/invites/{invite_id}/toggle", response_model=InviteResponse)
async def toggle_registration_invite(
    invite_id: int,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    invite = db.query(RegistrationInvite).filter(RegistrationInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请码不存在")

    invite.is_active = not invite.is_active
    write_admin_audit_log(
        db,
        admin_username,
        "toggle_invite",
        target_type="registration_invite",
        target_id=invite.id,
        detail={"is_active": invite.is_active},
    )
    db.commit()
    invite = (
        db.query(RegistrationInvite)
        .options(joinedload(RegistrationInvite.created_by_user), joinedload(RegistrationInvite.used_by_user))
        .filter(RegistrationInvite.id == invite_id)
        .one()
    )
    return serialize_registration_invite(invite)


@router.get("/announcements", response_model=List[AnnouncementResponse])
async def list_announcements(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> List[Announcement]:
    return (
        db.query(Announcement)
        .order_by(Announcement.created_at.desc(), Announcement.id.desc())
        .all()
    )


@router.post("/announcements", response_model=AnnouncementResponse)
async def create_announcement(
    payload: AnnouncementCreateRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Announcement:
    announcement = Announcement(
        title=payload.title.strip(),
        content=payload.content.strip(),
        category=payload.category,
        is_active=payload.is_active,
    )
    db.add(announcement)
    db.flush()
    write_admin_audit_log(
        db,
        admin_username,
        "create_announcement",
        target_type="announcement",
        target_id=announcement.id,
        detail={
            "title": announcement.title,
            "category": announcement.category,
            "is_active": announcement.is_active,
        },
    )
    db.commit()
    db.refresh(announcement)
    return announcement


@router.patch("/announcements/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementUpdateRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Announcement:
    announcement = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not announcement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公告不存在")

    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates and updates["title"] is not None:
        announcement.title = updates["title"].strip()
    if "content" in updates and updates["content"] is not None:
        announcement.content = updates["content"].strip()
    if "category" in updates and updates["category"] is not None:
        announcement.category = updates["category"]
    if "is_active" in updates and updates["is_active"] is not None:
        announcement.is_active = updates["is_active"]
    announcement.updated_at = utcnow()

    write_admin_audit_log(
        db,
        admin_username,
        "update_announcement",
        target_type="announcement",
        target_id=announcement.id,
        detail={"updated_keys": list(updates.keys())},
    )
    db.commit()
    db.refresh(announcement)
    return announcement


@router.post("/credit-codes/batch", response_model=List[CreditCodeResponse])
async def batch_create_credit_codes(
    payload: CreditCodeBatchCreateRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> List[CreditCode]:
    reserved_codes: set[str] = set()
    credit_codes: List[CreditCode] = []
    for _ in range(payload.quantity):
        code = _generate_unique_credit_code(db, reserved_codes)
        reserved_codes.add(code)
        credit_code = CreditCode(
            code=code,
            credit_amount=payload.credit_amount,
            is_active=True,
            expires_at=payload.expires_at,
        )
        db.add(credit_code)
        credit_codes.append(credit_code)

    db.flush()
    write_admin_audit_log(
        db,
        admin_username,
        "batch_create_credit_codes",
        target_type="credit_code",
        detail={
            "quantity": payload.quantity,
            "credit_amount": payload.credit_amount,
            "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
        },
    )
    db.commit()
    for credit_code in credit_codes:
        db.refresh(credit_code)
    return credit_codes


@router.get("/credit-codes/export")
async def export_credit_codes(
    export_format: str = Query("csv", alias="format", pattern="^(csv|txt)$"),
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Response:
    credit_codes = db.query(CreditCode).order_by(CreditCode.created_at.desc(), CreditCode.id.desc()).all()
    filename = f"gankaigc-credit-codes.{export_format}"

    if export_format == "txt":
        content = "\n".join(code.code for code in credit_codes)
        if content:
            content += "\n"
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["code", "credit_amount", "is_active", "redeemed_by_user_id", "created_at"])
    for code in credit_codes:
        writer.writerow(
            [
                code.code,
                code.credit_amount,
                code.is_active,
                code.redeemed_by_user_id or "",
                code.created_at.isoformat() if code.created_at else "",
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/credit-codes", response_model=CreditCodeResponse)
async def create_credit_code(
    payload: CreditCodeCreateRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> CreditCode:
    code = payload.code or _generate_unique_credit_code(db)
    existing_code = db.query(CreditCode).filter(CreditCode.code == code).first()
    if existing_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="兑换码已存在")

    credit_code = CreditCode(
        code=code,
        credit_amount=payload.credit_amount,
        is_active=True,
        expires_at=payload.expires_at,
    )
    db.add(credit_code)
    db.flush()
    write_admin_audit_log(
        db,
        admin_username,
        "create_credit_code",
        target_type="credit_code",
        target_id=credit_code.id,
        detail={
            "code": credit_code.code,
            "credit_amount": credit_code.credit_amount,
            "expires_at": credit_code.expires_at.isoformat() if credit_code.expires_at else None,
        },
    )
    db.commit()
    db.refresh(credit_code)
    return credit_code


@router.get("/credit-codes", response_model=List[CreditCodeResponse])
async def list_credit_codes(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> List[CreditCode]:
    return db.query(CreditCode).order_by(CreditCode.created_at.desc()).all()


@router.get("/credit-transactions")
async def list_credit_transactions(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = Query(None, ge=1),
) -> List[Dict[str, Any]]:
    query = (
        db.query(CreditTransaction)
        .options(
            joinedload(CreditTransaction.user),
            joinedload(CreditTransaction.related_session),
        )
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
    )
    if user_id is not None:
        query = query.filter(CreditTransaction.user_id == user_id)

    return [
        serialize_credit_transaction(transaction, include_user=True)
        for transaction in query.limit(limit).all()
    ]


@router.post("/users/{user_id}/credits")
async def add_user_credits(
    user_id: int,
    payload: AdminCreditAdjustRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    CreditService(db).add_credits(user, payload.amount, reason=payload.reason)
    write_admin_audit_log(
        db,
        admin_username,
        "add_user_credits",
        target_type="user",
        target_id=user.id,
        detail={"amount": payload.amount, "reason": payload.reason},
    )
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "credit_balance": user.credit_balance or 0,
        "is_unlimited": user.is_unlimited,
    }


@router.patch("/users/{user_id}/unlimited")
async def set_user_unlimited(
    user_id: int,
    payload: UnlimitedToggleRequest,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    user.is_unlimited = payload.is_unlimited
    write_admin_audit_log(
        db,
        admin_username,
        "set_user_unlimited",
        target_type="user",
        target_id=user.id,
        detail={"is_unlimited": user.is_unlimited},
    )
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "is_unlimited": user.is_unlimited,
        "credit_balance": user.credit_balance or 0,
    }


@router.get("/provider-configs")
async def list_provider_config_summaries(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    rows = (
        db.query(UserProviderConfig, User)
        .join(User, UserProviderConfig.user_id == User.id)
        .order_by(UserProviderConfig.updated_at.desc())
        .all()
    )
    return [
        {
            "user_id": user.id,
            "username": user.username,
            "base_url": config.base_url,
            "api_key_last4": config.api_key_last4,
            "polish_model": config.polish_model,
            "enhance_model": config.enhance_model,
            "emotion_model": config.emotion_model,
            "updated_at": config.updated_at,
        }
        for config, user in rows
    ]


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(_: str = Depends(get_admin_from_token), db: Session = Depends(get_db)) -> List[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}/toggle")
async def toggle_user_status(
    user_id: int,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = not user.is_active
    write_admin_audit_log(
        db,
        admin_username,
        "unban_user" if user.is_active else "ban_user",
        target_type="user",
        target_id=user.id,
        detail={"is_active": user.is_active},
    )
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "is_active": user.is_active,
        "message": f"用户已{'启用' if user.is_active else '禁用'}",
    }


@router.patch("/users/{user_id}/usage")
async def update_user_usage(
    user_id: int,
    payload: UserUsageUpdate,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.usage_limit = payload.usage_limit
    if payload.reset_usage_count:
        user.usage_count = 0
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "usage_limit": user.usage_limit,
        "usage_count": user.usage_count,
        "message": "使用限制已更新",
    }


@router.post("/sessions/{session_id}/stop")
async def admin_stop_session(
    session_id: str,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db)
):
    """管理员停止会话"""
    session = db.query(OptimizationSession).filter(
        OptimizationSession.session_id == session_id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
        
    if session.status not in ["queued", "processing"]:
        raise HTTPException(status_code=400, detail="只能停止排队中或处理中的会话")
        
    session.status = "stopped"
    session.error_message = "管理员手动停止"
    db.commit()
    
    return {"message": "会话已停止"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    db.delete(user)
    db.commit()
    return {"message": "用户已删除", "id": user_id}


@router.get("/statistics")
async def get_statistics(_: str = Depends(get_admin_from_token), db: Session = Depends(get_db)) -> Dict[str, Any]:
    total_users = db.query(User).count() or 0
    active_users = db.query(User).filter(User.is_active.is_(True)).count() or 0
    inactive_users = total_users - active_users
    used_users = db.query(User).filter(User.last_used.isnot(None)).count() or 0

    total_sessions = db.query(OptimizationSession).count() or 0
    completed_sessions = db.query(OptimizationSession).filter(OptimizationSession.status == "completed").count() or 0
    processing_sessions = db.query(OptimizationSession).filter(OptimizationSession.status == "processing").count() or 0
    queued_sessions = db.query(OptimizationSession).filter(OptimizationSession.status == "queued").count() or 0
    failed_sessions = db.query(OptimizationSession).filter(OptimizationSession.status == "failed").count() or 0

    total_segments = db.query(OptimizationSegment).count() or 0
    completed_segments = db.query(OptimizationSegment).filter(OptimizationSegment.status == "completed").count() or 0

    seven_days_ago = utcnow() - timedelta(days=7)
    recent_active_users = db.query(User).filter(User.last_used >= seven_days_ago).count() or 0

    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new_users = db.query(User).filter(User.created_at >= today_start).count() or 0
    today_active_users = db.query(User).filter(User.last_used >= today_start).count() or 0
    today_sessions = db.query(OptimizationSession).filter(OptimizationSession.created_at >= today_start).count() or 0
    
    # 统计文本处理字数
    all_sessions = db.query(OptimizationSession).filter(
        OptimizationSession.status == "completed"
    ).all()
    
    total_original_chars = sum(len(s.original_text) for s in all_sessions if s.original_text)
    
    # 统计各处理模式的使用量
    paper_polish_count = db.query(OptimizationSession).filter(
        OptimizationSession.processing_mode == "paper_polish"
    ).count() or 0

    paper_enhance_count = db.query(OptimizationSession).filter(
        OptimizationSession.processing_mode == "paper_enhance"
    ).count() or 0
    
    paper_polish_enhance_count = db.query(OptimizationSession).filter(
        OptimizationSession.processing_mode == "paper_polish_enhance"
    ).count() or 0
    
    emotion_polish_count = db.query(OptimizationSession).filter(
        OptimizationSession.processing_mode == "emotion_polish"
    ).count() or 0
    
    # 统计平均处理时间
    completed_with_time = db.query(OptimizationSession).filter(
        OptimizationSession.status == "completed",
        OptimizationSession.completed_at.isnot(None),
        OptimizationSession.created_at.isnot(None)
    ).all()
    
    avg_processing_time = 0
    if completed_with_time:
        total_time = sum(
            (s.completed_at - s.created_at).total_seconds() 
            for s in completed_with_time
        )
        avg_processing_time = total_time / len(completed_with_time)

    statistics = {
        "users": {
            "total": total_users,
            "active": active_users,
            "inactive": inactive_users,
            "used": used_users,
            "unused": total_users - used_users,
            "today_new": today_new_users,
            "today_active": today_active_users,
            "recent_active_7days": recent_active_users,
        },
        "sessions": {
            "total": total_sessions,
            "completed": completed_sessions,
            "processing": processing_sessions,
            "queued": queued_sessions,
            "failed": failed_sessions,
            "today": today_sessions,
        },
        "segments": {
            "total": total_segments,
            "completed": completed_segments,
            "pending": total_segments - completed_segments,
        },
        "processing": {
            "total_chars_processed": total_original_chars,
            "avg_processing_time": round(avg_processing_time, 2),
            "paper_polish_count": paper_polish_count,
            "paper_enhance_count": paper_enhance_count,
            "paper_polish_enhance_count": paper_polish_enhance_count,
            "emotion_polish_count": emotion_polish_count,
        },
    }

    if settings.WORD_FORMATTER_ENABLED:
        from app.word_formatter.services.job_manager import get_job_manager

        statistics["word_formatter"] = get_job_manager().get_stats()

    return statistics


@router.get("/users/{user_id}/details")
async def get_user_details(
    user_id: int,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user_sessions = db.query(OptimizationSession).filter(OptimizationSession.user_id == user_id).all()
    total_sessions = len(user_sessions)
    completed_sessions = sum(1 for session in user_sessions if session.status == "completed")

    session_ids = [session.id for session in user_sessions]
    total_segments = 0
    completed_segments = 0
    if session_ids:
        total_segments = db.query(OptimizationSegment).filter(OptimizationSegment.session_id.in_(session_ids)).count()
        completed_segments = (
            db.query(OptimizationSegment)
            .filter(OptimizationSegment.session_id.in_(session_ids), OptimizationSegment.status == "completed")
            .count()
        )

    recent_sessions = (
        db.query(OptimizationSession)
        .filter(OptimizationSession.user_id == user_id)
        .order_by(OptimizationSession.created_at.desc())
        .limit(5)
        .all()
    )
    recent_credit_transactions = (
        db.query(CreditTransaction)
        .options(joinedload(CreditTransaction.related_session))
        .filter(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
        .limit(10)
        .all()
    )

    return {
        "user": {
            "id": user.id,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_used": user.last_used,
            "usage_limit": user.usage_limit,
            "usage_count": user.usage_count,
        },
        "statistics": {
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "processing_sessions": total_sessions - completed_sessions,
            "total_segments": total_segments,
            "completed_segments": completed_segments,
        },
        "recent_sessions": [
            {
                "id": session.id,
                "status": session.status,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
            for session in recent_sessions
        ],
        "recent_credit_transactions": [
            serialize_credit_transaction(transaction)
            for transaction in recent_credit_transactions
        ],
    }


@router.get("/sessions")
async def get_all_sessions(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
    limit: int = 100,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """获取所有会话历史"""
    query = db.query(OptimizationSession).options(
        joinedload(OptimizationSession.user),
        defer(OptimizationSession.original_text),
        defer(OptimizationSession.error_message)
    ).order_by(OptimizationSession.created_at.desc())
    
    if status:
        query = query.filter(OptimizationSession.status == status)
    
    sessions = query.limit(limit).all()
    
    if not sessions:
        return []

    # 批量获取段落统计信息
    session_ids = [s.id for s in sessions]
    # 批量获取会话的原始文本长度
    original_lengths = db.query(
        OptimizationSession.id,
        func.length(OptimizationSession.original_text).label('length')
    ).filter(
        OptimizationSession.id.in_(session_ids)
    ).all()
    
    original_length_map = {item.id: (item.length or 0) for item in original_lengths}

    stats_query = db.query(
        OptimizationSegment.session_id,
        func.count(OptimizationSegment.id).label('total'),
        func.sum(case((OptimizationSegment.status == 'completed', 1), else_=0)).label('completed'),
        func.sum(func.length(func.coalesce(OptimizationSegment.polished_text, ''))).label('polished_chars'),
        func.sum(func.length(func.coalesce(OptimizationSegment.enhanced_text, ''))).label('enhanced_chars')
    ).filter(
        OptimizationSegment.session_id.in_(session_ids)
    ).group_by(OptimizationSegment.session_id).all()
    
    stats_map = {
        stat.session_id: {
            'total': stat.total,
            'completed': stat.completed,
            'polished_chars': stat.polished_chars or 0,
            'enhanced_chars': stat.enhanced_chars or 0
        }
        for stat in stats_query
    }
    
    result = []
    for session in sessions:
        # 计算处理时间
        processing_time = None
        if session.completed_at and session.created_at:
            processing_time = (session.completed_at - session.created_at).total_seconds()
        elif session.status == 'processing' and session.created_at:
            processing_time = (utcnow() - session.created_at).total_seconds()
        
        # 获取统计信息
        stats = stats_map.get(session.id, {
            'total': 0, 'completed': 0, 'polished_chars': 0, 'enhanced_chars': 0
        })
        
        result.append({
            "session_id": session.id,
            "user_id": session.user_id,
            **_session_user_identity(session.user),
            "status": session.status,
            "processing_mode": session.processing_mode,
            "original_char_count": original_length_map.get(session.id, 0),
            "polished_char_count": int(stats['polished_chars']),
            "enhanced_char_count": int(stats['enhanced_chars']),
            "total_segments": stats['total'],
            "completed_segments": stats['completed'],
            "progress": round((stats['completed'] / stats['total'] * 100) if stats['total'] > 0 else 0, 1),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "processing_time": processing_time,
            "error_message": None, # 列表页不返回详细错误信息
        })
    
    return result


@router.get("/sessions/active")
async def get_active_sessions(
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """获取所有活跃会话（处理中和排队中）- 优化版本，使用批量查询避免N+1问题"""
    # 使用 joinedload 预加载用户信息，避免N+1查询
    active_sessions = db.query(OptimizationSession).options(
        joinedload(OptimizationSession.user),
        defer(OptimizationSession.original_text)  # 延迟加载大文本字段
    ).filter(
        OptimizationSession.status.in_(["processing", "queued"])
    ).order_by(OptimizationSession.created_at.desc()).all()

    if not active_sessions:
        return []

    # 批量获取会话ID
    session_ids = [s.id for s in active_sessions]

    # 批量查询原文长度和预览（避免加载完整文本）
    text_info = db.query(
        OptimizationSession.id,
        func.length(OptimizationSession.original_text).label('length'),
        func.substring(OptimizationSession.original_text, 1, 200).label('preview')
    ).filter(
        OptimizationSession.id.in_(session_ids)
    ).all()
    text_info_map = {
        item.id: {'length': item.length or 0, 'preview': item.preview or ""}
        for item in text_info
    }

    # 批量查询已完成段落数
    segments_stats = db.query(
        OptimizationSegment.session_id,
        func.sum(case((OptimizationSegment.status == 'completed', 1), else_=0)).label('completed')
    ).filter(
        OptimizationSegment.session_id.in_(session_ids)
    ).group_by(OptimizationSegment.session_id).all()

    segments_map = {stat.session_id: int(stat.completed or 0) for stat in segments_stats}

    result = []
    now = utcnow()
    for session in active_sessions:
        # 计算处理时间
        processing_time = None
        if session.status == "processing" and session.created_at:
            processing_time = (now - session.created_at).total_seconds()

        text_data = text_info_map.get(session.id, {'length': 0, 'preview': ""})

        result.append({
            "id": session.id,
            "session_id": session.session_id,
            "user_id": session.user_id,
            **_session_user_identity(session.user),
            "status": session.status,
            "progress": session.progress,
            "current_stage": session.current_stage,
            "current_position": session.current_position,
            "total_segments": session.total_segments,
            "processed_segments": segments_map.get(session.id, 0),
            "original_text": text_data['preview'],
            "original_char_count": text_data['length'],
            "processing_mode": session.processing_mode,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "processing_time": processing_time,
            "error_message": session.error_message
        })

    return result


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(
    user_id: int,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """获取指定用户的所有会话历史"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    sessions = db.query(OptimizationSession).options(
        defer(OptimizationSession.original_text),
        defer(OptimizationSession.error_message)
    ).filter(
        OptimizationSession.user_id == user_id
    ).order_by(OptimizationSession.created_at.desc()).limit(50).all()
    
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    
    # 批量获取会话的原始文本长度和预览
    original_info = db.query(
        OptimizationSession.id,
        func.length(OptimizationSession.original_text).label('length'),
        func.substring(OptimizationSession.original_text, 1, 100).label('preview')
    ).filter(
        OptimizationSession.id.in_(session_ids)
    ).all()
    
    original_info_map = {
        item.id: {'length': item.length or 0, 'preview': item.preview or ""}
        for item in original_info
    }

    stats_query = db.query(
        OptimizationSegment.session_id,
        func.count(OptimizationSegment.id).label('total'),
        func.sum(case((OptimizationSegment.status == 'completed', 1), else_=0)).label('completed'),
        func.sum(func.length(func.coalesce(OptimizationSegment.polished_text, ''))).label('polished_chars'),
        func.sum(func.length(func.coalesce(OptimizationSegment.enhanced_text, ''))).label('enhanced_chars')
    ).filter(
        OptimizationSegment.session_id.in_(session_ids)
    ).group_by(OptimizationSegment.session_id).all()
    
    stats_map = {
        stat.session_id: {
            'total': stat.total,
            'completed': stat.completed,
            'polished_chars': stat.polished_chars or 0,
            'enhanced_chars': stat.enhanced_chars or 0
        }
        for stat in stats_query
    }
    
    result = []
    for session in sessions:
        # 计算处理时间
        processing_time = None
        if session.completed_at and session.created_at:
            processing_time = (session.completed_at - session.created_at).total_seconds()
        elif session.status == "processing" and session.created_at:
            processing_time = (utcnow() - session.created_at).total_seconds()
        
        stats = stats_map.get(session.id, {
            'total': 0, 'completed': 0, 'polished_chars': 0, 'enhanced_chars': 0
        })
        
        orig_info = original_info_map.get(session.id, {'length': 0, 'preview': ""})

        result.append({
            "id": session.id,
            "session_id": session.session_id,
            "status": session.status,
            "processing_mode": session.processing_mode,
            "original_text": orig_info['preview'],
            "original_char_count": orig_info['length'],
            "polished_char_count": int(stats['polished_chars']),
            "enhanced_char_count": int(stats['enhanced_chars']),
            "total_segments": stats['total'],
            "completed_segments": stats['completed'],
            "progress": session.progress,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "processing_time": processing_time,
            "error_message": None # 列表页不返回详细错误信息
        })
    
    return result


@router.get("/config")
async def get_config(_: str = Depends(get_admin_from_token)) -> Dict[str, Any]:
    return {
        "polish": {
            "model": settings.POLISH_MODEL,
            "api_key": settings.POLISH_API_KEY or "",
            "base_url": settings.POLISH_BASE_URL or "",
        },
        "enhance": {
            "model": settings.ENHANCE_MODEL,
            "api_key": settings.ENHANCE_API_KEY or "",
            "base_url": settings.ENHANCE_BASE_URL or "",
        },
        "emotion": {
            "model": getattr(settings, 'EMOTION_MODEL', settings.POLISH_MODEL),
            "api_key": getattr(settings, 'EMOTION_API_KEY', settings.POLISH_API_KEY) or "",
            "base_url": getattr(settings, 'EMOTION_BASE_URL', settings.POLISH_BASE_URL) or "",
        },
        "compression": {
            "model": settings.COMPRESSION_MODEL,
            "api_key": settings.COMPRESSION_API_KEY or "",
            "base_url": settings.COMPRESSION_BASE_URL or "",
        },
        "thinking": {
            "enabled": settings.THINKING_MODE_ENABLED,
            "effort": settings.THINKING_MODE_EFFORT,
        },
        "system": {
            "max_concurrent_users": settings.MAX_CONCURRENT_USERS,
            "history_compression_threshold": settings.HISTORY_COMPRESSION_THRESHOLD,
            "default_usage_limit": settings.DEFAULT_USAGE_LIMIT,
            "segment_skip_threshold": settings.SEGMENT_SKIP_THRESHOLD,
            "use_streaming": settings.USE_STREAMING,
            "max_upload_file_size_mb": settings.MAX_UPLOAD_FILE_SIZE_MB,
            "api_request_interval": settings.API_REQUEST_INTERVAL,
            "registration_enabled": settings.REGISTRATION_ENABLED,
        },
    }


@router.post("/config")
async def update_config(
    updates: Dict[str, str],
    request: Request,
    admin_username: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少更新内容")

    # 使用 config.py 中的函数获取 .env 路径，支持 exe 环境
    from app.config import get_env_file_path
    env_path = get_env_file_path()

    env_existed = os.path.exists(env_path)
    if env_existed:
        with open(env_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    else:
        lines = []

    updated_keys = set()
    new_lines: List[str] = []
    for line in lines:
        stripped = line.rstrip("\n")
        if "=" in stripped and not stripped.strip().startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    original_content = "".join(lines)
    new_content = "".join(new_lines)

    try:
        env_dir = os.path.dirname(env_path)
        if env_dir:
            os.makedirs(env_dir, exist_ok=True)
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write(new_content)

        reload_settings(updates)
        refresh_cors_middleware(request.app)
    except Exception as exc:
        if env_existed:
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write(original_content)
        elif os.path.exists(env_path):
            os.remove(env_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if "MAX_CONCURRENT_USERS" in updates:
        try:
            await concurrency_manager.update_limit(int(updates["MAX_CONCURRENT_USERS"]))
        except ValueError:
            pass

    write_admin_audit_log(
        db,
        admin_username,
        "update_config",
        target_type="system_config",
        detail={"updated_keys": list(updates.keys())},
    )
    db.commit()

    return {"message": "配置已更新并保存", "updated_keys": list(updates.keys())}


@router.get("/database/tables")
async def list_tables(_: str = Depends(get_admin_from_token)) -> Dict[str, Any]:
    _ensure_database_manager_enabled()
    return {
        "tables": list(ALLOWED_TABLES.keys()),
        "can_write": settings.ADMIN_DATABASE_WRITE_ENABLED,
        "max_page_size": DATABASE_MANAGER_MAX_PAGE_SIZE,
    }


@router.get("/database/{table_name}")
async def fetch_table_records(
    table_name: str,
    skip: int = 0,
    limit: int = 50,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_database_manager_enabled()
    if table_name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="表不存在或不允许访问")

    model = ALLOWED_TABLES[table_name]
    page_size = max(min(limit, DATABASE_MANAGER_MAX_PAGE_SIZE), 1)
    safe_skip = max(skip, 0)
    query = db.query(model)
    if hasattr(model, "id"):
        query = query.order_by(getattr(model, "id").desc())
    query = query.offset(safe_skip).limit(page_size)
    records = [sanitize_db_record(_model_to_dict(row)) for row in query.all()]
    total = db.query(model).count()
    return {
        "total": total,
        "items": records,
        "skip": safe_skip,
        "limit": page_size,
        "can_write": settings.ADMIN_DATABASE_WRITE_ENABLED,
    }


@router.put("/database/{table_name}/{record_id}")
async def update_table_record(
    table_name: str,
    record_id: int,
    payload: DatabaseUpdateRequest,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_database_write_enabled()
    if table_name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="表不存在或不允许访问")

    model = ALLOWED_TABLES[table_name]
    record = db.query(model).filter(getattr(model, "id") == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    mapper = inspect(model)
    allowed_columns = {
        column.key
        for column in mapper.columns
        if not column.primary_key and column.key.lower() not in SENSITIVE_DB_FIELDS
    }

    for key, value in payload.data.items():
        if isinstance(record, SystemSetting) and key == "value" and _is_sensitive_system_setting_key(record.key):
            raise HTTPException(status_code=400, detail="敏感系统配置不能通过数据库管理器修改")
        if key in allowed_columns:
            setattr(record, key, value)

    db.commit()
    db.refresh(record)
    return {"message": "记录已更新", "record": sanitize_db_record(_model_to_dict(record))}


@router.delete("/database/{table_name}/{record_id}")
async def delete_table_record(
    table_name: str,
    record_id: int,
    _: str = Depends(get_admin_from_token),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    _ensure_database_write_enabled()
    if table_name not in ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail="表不存在或不允许访问")

    model = ALLOWED_TABLES[table_name]
    record = db.query(model).filter(getattr(model, "id") == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    db.delete(record)
    db.commit()
    return {"message": "记录已删除"}
