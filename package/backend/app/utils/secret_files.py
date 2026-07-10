"""Strict file-secret reader shared by runtime and one-shot tooling."""

from pathlib import Path
import stat


MAX_SECRET_FILE_BYTES = 64 * 1024


def read_secret_file(secret_name: str, file_path: str) -> str:
    """Read a 0600 UTF-8 secret without including its value in errors."""
    path = Path(file_path)
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise RuntimeError(
            f"Unable to read {secret_name} file at {path}: {exc.strerror or exc}"
        ) from exc

    if not stat.S_ISREG(file_stat.st_mode):
        raise RuntimeError(f"{secret_name} must point to a regular file: {path}")
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise RuntimeError(
            f"{secret_name} must not be accessible by group/others; chmod 600 {path}"
        )
    if file_stat.st_size > MAX_SECRET_FILE_BYTES:
        raise RuntimeError(f"{secret_name} exceeds the 64 KiB safety limit: {path}")

    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Unable to decode {secret_name} file at {path}") from exc
    if not value:
        raise RuntimeError(f"{secret_name} file is empty: {path}")
    if "\x00" in value:
        raise RuntimeError(f"{secret_name} file contains an invalid NUL byte: {path}")
    return value
