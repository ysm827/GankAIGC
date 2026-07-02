from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import RegistrationInvite, User
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    UserPasswordUpdateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from app.utils.auth import (
    create_user_access_token,
    get_password_hash,
    verify_password,
    verify_user_token,
)
from app.utils.time import to_china_naive, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


def get_current_user_from_bearer(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证令牌")

    token = authorization.split(" ", 1)[1]
    payload = verify_user_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")

    user_id = payload.get("sub")
    if not user_id or not str(user_id).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")

    user = db.query(User).filter(User.id == int(user_id), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    if int(payload.get("token_version", 0)) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录")
    return user


@router.post("/register", response_model=UserProfileResponse)
async def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前已关闭新用户注册")

    now = utcnow()
    invite = (
        db.query(RegistrationInvite)
        .filter(
            RegistrationInvite.code == payload.invite_code,
            RegistrationInvite.is_active.is_(True),
        )
        .first()
    )
    expires_at = to_china_naive(invite.expires_at if invite else None)
    if not invite or (expires_at and expires_at < now):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码无效")

    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    user = User(
        username=payload.username,
        nickname=payload.username,
        password_hash=get_password_hash(payload.password),
        access_link=f"account://{payload.username}",
        is_active=True,
        credit_balance=0,
        usage_limit=0,
        usage_count=0,
    )
    db.add(user)
    db.flush()
    invite.is_active = False
    invite.used_by_user_id = user.id
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(User.username == payload.username)
        .first()
    )
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁，请联系管理员")

    user.last_login_at = utcnow()
    if user.token_version is None:
        user.token_version = 0
    db.commit()
    token = create_user_access_token(user.id, user.username or "", token_version=user.token_version or 0)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserProfileResponse.model_validate(user),
    }


@router.get("/me", response_model=UserProfileResponse)
async def me(current_user: User = Depends(get_current_user_from_bearer)) -> User:
    return current_user


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
) -> User:
    nickname = payload.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="昵称不能为空")

    current_user.nickname = nickname
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password")
async def update_my_password(
    payload: UserPasswordUpdateRequest,
    current_user: User = Depends(get_current_user_from_bearer),
    db: Session = Depends(get_db),
):
    if not current_user.password_hash or not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能和当前密码相同")

    current_user.password_hash = get_password_hash(payload.new_password)
    current_user.token_version = int(current_user.token_version or 0) + 1
    db.commit()
    return {"message": "密码已更新"}
