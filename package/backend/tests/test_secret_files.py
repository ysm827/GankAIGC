import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.config as config_module
from app.routes import admin as admin_module
from app.utils.secret_files import read_secret_file


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _secret_file(tmp_path, name: str, value: str):
    path = tmp_path / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_secret_file_reader_requires_private_permissions(tmp_path):
    path = tmp_path / "secret_key"
    path.write_text("never-logged", encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(RuntimeError, match="chmod 600") as exc_info:
        read_secret_file("SECRET_KEY_FILE", str(path))

    assert "never-logged" not in str(exc_info.value)


def test_secret_file_reader_removes_only_trailing_newlines(tmp_path):
    path = _secret_file(tmp_path, "secret_key", "  value with spaces  ")

    assert read_secret_file("SECRET_KEY_FILE", str(path)) == "  value with spaces  "


def test_file_secret_overrides_environment_and_runtime_reload(monkeypatch, tmp_path):
    path = _secret_file(tmp_path, "secret_key", "file-backed-secret-key-32-characters")
    original_secret = config_module.settings.SECRET_KEY
    original_app_env = config_module.settings.APP_ENV

    monkeypatch.setenv("SECRET_KEY", "environment-secret-key-32-characters")
    monkeypatch.setenv("SECRET_KEY_FILE", str(path))
    monkeypatch.setattr(config_module.settings, "APP_ENV", "development")
    monkeypatch.setattr(config_module.settings, "SECRET_KEY", original_secret)
    try:
        config_module.reload_settings(
            {
                "APP_ENV": "development",
                "SECRET_KEY": "admin-ui-secret-key-32-characters",
            }
        )
        assert config_module.settings.SECRET_KEY == "file-backed-secret-key-32-characters"
        assert os.environ["SECRET_KEY"] == "environment-secret-key-32-characters"
        assert "SECRET_KEY" in config_module.get_file_backed_settings()
    finally:
        config_module.settings.SECRET_KEY = original_secret
        config_module.settings.APP_ENV = original_app_env


def test_file_secret_is_loaded_before_settings_singleton(tmp_path):
    path = _secret_file(tmp_path, "secret_key", "import-time-file-secret-32-characters")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_FILE")
    }
    environment.update(
        {
            "PYTHONPATH": str(BACKEND_DIR),
            "GANKAIGC_ENV_FILE": str(tmp_path / "missing.env"),
            "APP_ENV": "development",
            "SECRET_KEY": "environment-secret-32-characters",
            "SECRET_KEY_FILE": str(path),
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; from app.config import settings; "
            "print(settings.SECRET_KEY == 'import-time-file-secret-32-characters' "
            "and os.environ['SECRET_KEY'] == 'environment-secret-32-characters')",
        ],
        cwd=BACKEND_DIR,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "True"


def test_provider_api_keys_support_file_secrets(monkeypatch, tmp_path):
    path = _secret_file(tmp_path, "polish_api_key", "provider-file-secret")
    monkeypatch.setenv("POLISH_API_KEY", "environment-provider-secret")
    monkeypatch.setenv("POLISH_API_KEY_FILE", str(path))

    values = config_module.read_secret_file_values()

    assert values["POLISH_API_KEY"] == "provider-file-secret"


def test_admin_cannot_overwrite_file_backed_secret(monkeypatch, tmp_path):
    secret_path = _secret_file(tmp_path, "polish_api_key", "provider-file-secret")
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("POLISH_MODEL=old-model\n", encoding="utf-8")
    monkeypatch.setenv("POLISH_API_KEY_FILE", str(secret_path))
    monkeypatch.setattr(config_module, "get_env_file_path", lambda: str(runtime_env))

    with pytest.raises(ValueError, match=r"\*_FILE Secret"):
        admin_module._persist_runtime_env_updates({"POLISH_API_KEY": "replacement"})

    assert runtime_env.read_text(encoding="utf-8") == "POLISH_MODEL=old-model\n"
