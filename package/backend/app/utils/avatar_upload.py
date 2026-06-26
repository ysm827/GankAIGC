from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Final

from fastapi import HTTPException, UploadFile, status

AVATAR_MAX_BYTES: Final[int] = 2 * 1024 * 1024
AVATAR_UPLOAD_SUBDIR: Final[tuple[str, str]] = ("uploads", "avatars")
AVATAR_ALLOWED_CONTENT_TYPES: Final[dict[str, str]] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
AVATAR_ALLOWED_EXTENSIONS: Final[set[str]] = {".png", ".jpg", ".jpeg", ".webp"}


def get_static_root() -> Path:
    """Return the writable static root used for user-uploaded public files."""
    if getattr(sys, "frozen", False):
        return Path.cwd() / "static"
    return Path(__file__).resolve().parents[3] / "static"


def get_avatar_upload_dir() -> Path:
    return get_static_root().joinpath(*AVATAR_UPLOAD_SUBDIR)


def get_uploads_mount_dir() -> Path:
    return get_static_root() / "uploads"


def _detect_avatar_suffix(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


async def read_upload_file_with_limit(file: UploadFile, max_bytes: int = AVATAR_MAX_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="头像文件不能超过 2MB",
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件不能为空")
    return content


async def save_avatar_upload(file: UploadFile) -> str:
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in AVATAR_ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="头像仅支持 PNG、JPG、WebP 图片",
        )

    filename_suffix = Path(file.filename or "").suffix.lower()
    if filename_suffix not in AVATAR_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="头像文件扩展名仅支持 png、jpg、jpeg、webp",
        )

    content = await read_upload_file_with_limit(file)
    detected_suffix = _detect_avatar_suffix(content)
    expected_suffix = AVATAR_ALLOWED_CONTENT_TYPES[content_type]
    if not detected_suffix or detected_suffix != expected_suffix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="头像文件格式不正确",
        )

    upload_dir = get_avatar_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_urlsafe(18)}{detected_suffix}"
    target = upload_dir / filename
    target.write_bytes(content)
    return f"/uploads/avatars/{filename}"
