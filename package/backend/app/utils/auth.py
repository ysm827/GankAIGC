import secrets
from datetime import timedelta
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings
from app.database import get_db
from app.models.models import User
from app.utils.time import utc_naive_now, utcnow
from sqlalchemy.orm import Session


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_session_id() -> str:
    """生成会话ID"""
    return secrets.token_urlsafe(32)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = utc_naive_now() + expires_delta
    else:
        expire = utc_naive_now() + timedelta(minutes=settings.USER_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_user_access_token(
    user_id: int,
    username: str,
    expires_delta: Optional[timedelta] = None,
    token_version: int = 0,
) -> str:
    return create_access_token(
        {"sub": str(user_id), "username": username, "role": "user", "token_version": token_version},
        expires_delta=expires_delta,
    )


def create_stream_access_token(user_id: int, session_id: str, token_version: int = 0) -> str:
    """Create a short-lived token limited to one SSE session stream."""
    return create_access_token(
        {
            "sub": str(user_id),
            "role": "stream",
            "scope": "session_stream",
            "session_id": session_id,
            "token_version": token_version,
        },
        expires_delta=timedelta(seconds=settings.STREAM_TOKEN_EXPIRE_SECONDS),
    )


def verify_token(token: str) -> Optional[dict]:
    """验证令牌"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def verify_user_token(token: str) -> Optional[dict]:
    payload = verify_token(token)
    if payload and payload.get("role") == "user":
        return payload
    return None


def verify_stream_token(token: str) -> Optional[dict]:
    payload = verify_token(token)
    if (
        payload
        and payload.get("role") == "stream"
        and payload.get("scope") == "session_stream"
        and payload.get("session_id")
    ):
        return payload
    return None


def get_current_user_from_bearer(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    token = authorization.split(" ", 1)[1] if authorization and authorization.startswith("Bearer ") else None
    payload = verify_user_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")

    user_id = payload.get("sub")
    if not user_id or not str(user_id).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")

    user = db.query(User).filter(User.id == int(user_id), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    if int(payload.get("token_version", 0)) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录")

    user.last_used = utcnow()
    db.commit()
    return user


def get_current_user_with_legacy_fallback(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Return the current user from Authorization header only.

    The historical query-string access_token fallback was intentionally removed:
    long-lived login tokens must not travel in URLs or server/proxy logs.
    """
    return get_current_user_from_bearer(authorization, db)


def get_user_from_stream_token(
    stream_token: str,
    session_id: str,
    db: Session,
) -> User:
    payload = verify_stream_token(stream_token)
    if not payload or payload.get("session_id") != session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="实时连接凭据无效或已过期")

    user_id = payload.get("sub")
    if not user_id or not str(user_id).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="实时连接凭据无效或已过期")

    user = db.query(User).filter(User.id == int(user_id), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    if int(payload.get("token_version", 0)) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录")

    user.last_used = utcnow()
    db.commit()
    return user
