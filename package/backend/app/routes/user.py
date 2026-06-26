import secrets
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, status, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models.models import Announcement, CreditTransaction, PaperProject, RegistrationInvite, User
from app.routes.auth import get_current_user_from_bearer
from app.schemas import (
    CreditBalanceResponse,
    CreditTransactionResponse,
    AnnouncementResponse,
    PaperProjectCreate,
    PaperProjectResponse,
    PaperProjectUpdate,
    ProviderModelListRequest,
    ProviderModelTestRequest,
    ProviderConfigResponse,
    ProviderConfigUpdateRequest,
    RedeemCodeRequest,
    UserInviteResponse,
    UserProfileResponse,
)
from app.services.credit_service import CreditService, serialize_credit_transaction
from app.services import operations_service
from app.services.ai_service import normalize_api_format
from app.services.provider_config_service import ProviderConfigService
from app.utils.url_security import validate_model_base_url
from app.utils.avatar_upload import save_avatar_upload

router = APIRouter(prefix="/user", tags=["user"])


def _generate_unique_invite_code(db: Session) -> str:
    for _ in range(10):
        code = secrets.token_urlsafe(18)
        existing_invite = db.query(RegistrationInvite).filter(RegistrationInvite.code == code).first()
        if not existing_invite:
            return code
    raise HTTPException(status_code=500, detail="邀请码生成失败，请重试")


def _validate_user_provider_base_url(base_url: str) -> str:
    try:
        return validate_model_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_user_provider_api_format(api_format: str) -> str:
    try:
        return normalize_api_format(api_format)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_user_provider_model(model: str) -> str:
    value = (model or "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模型名称未配置")
    return value


def _mark_user_provider_result(result: dict) -> dict:
    return {
        **result,
        "stage": "provider",
        "label": "自带 API",
    }


@router.get("/announcements", response_model=List[AnnouncementResponse])
async def list_active_announcements(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> List[Announcement]:
    return (
        db.query(Announcement)
        .filter(Announcement.is_active.is_(True))
        .order_by(Announcement.created_at.desc(), Announcement.id.desc())
        .limit(10)
        .all()
    )


@router.get("/invites/my", response_model=UserInviteResponse | None)
async def get_my_registration_invite(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> RegistrationInvite | None:
    return (
        db.query(RegistrationInvite)
        .filter(
            RegistrationInvite.created_by_user_id == current_user.id,
        )
        .order_by(RegistrationInvite.created_at.desc())
        .first()
    )


@router.post("/invites", response_model=UserInviteResponse)
async def create_my_registration_invite(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> RegistrationInvite:
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前已关闭新用户注册")

    existing_invite = (
        db.query(RegistrationInvite)
        .filter(
            RegistrationInvite.created_by_user_id == current_user.id,
        )
        .order_by(RegistrationInvite.created_at.desc())
        .first()
    )
    if existing_invite:
        return existing_invite

    invite = RegistrationInvite(
        code=_generate_unique_invite_code(db),
        is_active=True,
        created_by_user_id=current_user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/projects", response_model=List[PaperProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> List[PaperProject]:
    return (
        db.query(PaperProject)
        .filter(PaperProject.user_id == current_user.id, PaperProject.is_archived.is_(False))
        .order_by(PaperProject.updated_at.desc(), PaperProject.created_at.desc())
        .all()
    )


@router.post("/projects", response_model=PaperProjectResponse)
async def create_project(
    payload: PaperProjectCreate,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> PaperProject:
    project = PaperProject(
        user_id=current_user.id,
        title=payload.title.strip(),
        description=payload.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=PaperProjectResponse)
async def update_project(
    project_id: int,
    payload: PaperProjectUpdate,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> PaperProject:
    project = (
        db.query(PaperProject)
        .filter(PaperProject.id == project_id, PaperProject.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")

    if payload.title is not None:
        project.title = payload.title.strip()
    if payload.description is not None:
        project.description = payload.description
    if payload.is_archived is not None:
        project.is_archived = payload.is_archived

    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", response_model=PaperProjectResponse)
async def archive_project(
    project_id: int,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> PaperProject:
    project = (
        db.query(PaperProject)
        .filter(PaperProject.id == project_id, PaperProject.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="论文项目不存在")

    project.is_archived = True
    db.commit()
    db.refresh(project)
    return project


@router.post("/redeem-code", response_model=CreditBalanceResponse)
async def redeem_code(
    payload: RedeemCodeRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> CreditBalanceResponse:
    CreditService(db).redeem_code(current_user, payload.code)
    db.commit()
    db.refresh(current_user)
    return CreditBalanceResponse(
        credit_balance=current_user.credit_balance or 0,
        is_unlimited=current_user.is_unlimited,
    )


@router.get("/credits", response_model=CreditBalanceResponse)
async def get_credits(current_user: User = Depends(get_current_user_from_bearer)) -> CreditBalanceResponse:
    return CreditBalanceResponse(
        credit_balance=current_user.credit_balance or 0,
        is_unlimited=current_user.is_unlimited,
    )


@router.get("/credit-transactions", response_model=List[CreditTransactionResponse])
async def list_credit_transactions(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
) -> List[dict]:
    transactions = (
        db.query(CreditTransaction)
        .options(joinedload(CreditTransaction.related_session))
        .filter(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_credit_transaction(transaction) for transaction in transactions]


@router.post("/profile/avatar", response_model=UserProfileResponse)
async def upload_my_profile_avatar(
    avatar: UploadFile = File(...),
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> User:
    current_user.avatar_url = await save_avatar_upload(avatar)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/provider-config", response_model=ProviderConfigResponse | None)
async def get_provider_config(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
):
    return ProviderConfigService(db).get_masked_config(current_user)


@router.put("/provider-config", response_model=ProviderConfigResponse)
async def save_provider_config(
    payload: ProviderConfigUpdateRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> ProviderConfigResponse:
    service = ProviderConfigService(db)
    service.save_config(current_user, payload)
    db.commit()
    return service.get_masked_config(current_user)


@router.post("/provider-config/test")
async def test_provider_config(
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
):
    provider_config = ProviderConfigService(db).get_runtime_config(current_user)
    result = await operations_service.test_provider_model_connection(provider_config)
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.post("/provider-config/model-list")
async def list_provider_config_models(
    payload: ProviderModelListRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
):
    service = ProviderConfigService(db)
    api_key = service.resolve_transient_api_key(current_user, payload.api_key)
    base_url = _validate_user_provider_base_url(payload.base_url)
    api_format = _validate_user_provider_api_format(payload.api_format)
    result = await operations_service.list_provider_models(
        "polish",
        base_url=base_url,
        api_key=api_key,
        api_format=api_format,
    )
    result = _mark_user_provider_result(result)
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.post("/provider-config/model-test")
async def test_provider_config_model(
    payload: ProviderModelTestRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
):
    service = ProviderConfigService(db)
    api_key = service.resolve_transient_api_key(current_user, payload.api_key)
    model = _validate_user_provider_model(payload.model)
    base_url = _validate_user_provider_base_url(payload.base_url)
    api_format = _validate_user_provider_api_format(payload.api_format)
    result = await operations_service.test_model_connection(
        "polish",
        model=model,
        base_url=base_url,
        api_key=api_key,
        api_format=api_format,
    )
    result = _mark_user_provider_result(result)
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result
