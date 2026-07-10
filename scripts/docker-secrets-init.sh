#!/usr/bin/env sh
set -eu
umask 077

project_dir="${GANKAIGC_HOST_PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
env_file="${GANKAIGC_DOCKER_ENV_FILE:-$project_dir/.env.docker}"
secrets_dir="${GANKAIGC_SECRETS_DIR:-$project_dir/secrets}"

[ -f "$env_file" ] || {
  echo "Missing $env_file; copy .env.docker.example first" >&2
  exit 1
}

env_value() {
  key="$1"
  fallback="$2"
  value="$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)"
  case "$value" in
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
  esac
  printf '%s' "${value:-$fallback}"
}

runtime_uid="$(env_value GANKAIGC_RUNTIME_UID "$(id -u)")"
runtime_gid="$(env_value GANKAIGC_RUNTIME_GID "$(id -g)")"
bootstrap_role="$(env_value POSTGRES_BOOTSTRAP_ROLE ai_polish)"
owner_role="$(env_value POSTGRES_OWNER_ROLE gankaigc_owner)"
migrator_role="$(env_value POSTGRES_MIGRATOR_ROLE gankaigc_migrator)"
app_role="$(env_value POSTGRES_APP_ROLE gankaigc_app)"
backup_role="$(env_value POSTGRES_BACKUP_ROLE gankaigc_backup)"
existing_postgres_password="$(env_value POSTGRES_PASSWORD '')"
existing_secret_key="$(env_value SECRET_KEY '')"
existing_admin_password="$(env_value ADMIN_PASSWORD '')"
existing_encryption_key="$(env_value ENCRYPTION_KEY '')"
existing_openai_api_key="$(env_value OPENAI_API_KEY '')"
existing_polish_api_key="$(env_value POLISH_API_KEY '')"
existing_enhance_api_key="$(env_value ENHANCE_API_KEY '')"
existing_emotion_api_key="$(env_value EMOTION_API_KEY '')"
existing_compression_api_key="$(env_value COMPRESSION_API_KEY '')"
existing_restic_password="$(env_value RESTIC_PASSWORD '')"

for role in "$bootstrap_role" "$owner_role" "$migrator_role" "$app_role" "$backup_role"; do
  case "$role" in
    ''|*[!A-Za-z0-9_]*) echo "Invalid PostgreSQL role name in $env_file" >&2; exit 1 ;;
  esac
done

secret_files="postgres_password bootstrap_database_url migrator_database_url app_database_url migrator_password app_password backup_password secret_key admin_password encryption_key openai_api_key polish_api_key enhance_api_key emotion_api_key compression_api_key restic_password"
mkdir -p "$secrets_dir"
chmod 700 "$secrets_dir"
for name in $secret_files; do
  if [ -e "$secrets_dir/$name" ]; then
    echo "Refusing to overwrite existing secret: $secrets_dir/$name" >&2
    exit 1
  fi
done

SECRETS_DIR="$secrets_dir" \
POSTGRES_BOOTSTRAP_ROLE="$bootstrap_role" \
POSTGRES_MIGRATOR_ROLE="$migrator_role" \
POSTGRES_APP_ROLE="$app_role" \
EXISTING_POSTGRES_PASSWORD="$existing_postgres_password" \
EXISTING_SECRET_KEY="$existing_secret_key" \
EXISTING_ADMIN_PASSWORD="$existing_admin_password" \
EXISTING_ENCRYPTION_KEY="$existing_encryption_key" \
EXISTING_OPENAI_API_KEY="$existing_openai_api_key" \
EXISTING_POLISH_API_KEY="$existing_polish_api_key" \
EXISTING_ENHANCE_API_KEY="$existing_enhance_api_key" \
EXISTING_EMOTION_API_KEY="$existing_emotion_api_key" \
EXISTING_COMPRESSION_API_KEY="$existing_compression_api_key" \
EXISTING_RESTIC_PASSWORD="$existing_restic_password" \
python3 - <<'PY'
import base64
import os
from pathlib import Path
import secrets
from urllib.parse import quote

root = Path(os.environ["SECRETS_DIR"])
bootstrap_role = os.environ["POSTGRES_BOOTSTRAP_ROLE"]
migrator_role = os.environ["POSTGRES_MIGRATOR_ROLE"]
app_role = os.environ["POSTGRES_APP_ROLE"]

def existing_or_random(name: str, generator) -> str:
    value = os.environ.get(name, "").strip()
    lowered = value.lower()
    placeholders = ("replace-with", "change-this", "your-secret-key", "admin123")
    return generator() if not value or any(marker in lowered for marker in placeholders) else value

def provider_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    lowered = value.lower()
    if not value or any(marker in lowered for marker in ("replace-with", "change-this")):
        return "pwd"
    return value

passwords = {
    "postgres_password": existing_or_random(
        "EXISTING_POSTGRES_PASSWORD", lambda: secrets.token_urlsafe(36)
    ),
    "migrator_password": secrets.token_urlsafe(36),
    "app_password": secrets.token_urlsafe(36),
    "backup_password": secrets.token_urlsafe(36),
}
for name, value in passwords.items():
    (root / name).write_text(value + "\n", encoding="utf-8")

def database_url(role: str, password: str) -> str:
    return (
        f"postgresql://{quote(role, safe='')}:{quote(password, safe='')}"
        "@postgres:5432/ai_polish"
    )

(root / "bootstrap_database_url").write_text(
    database_url(bootstrap_role, passwords["postgres_password"]) + "\n",
    encoding="utf-8",
)
(root / "migrator_database_url").write_text(
    database_url(migrator_role, passwords["migrator_password"]) + "\n",
    encoding="utf-8",
)
(root / "app_database_url").write_text(
    database_url(app_role, passwords["app_password"]) + "\n",
    encoding="utf-8",
)
(root / "secret_key").write_text(
    existing_or_random("EXISTING_SECRET_KEY", lambda: secrets.token_urlsafe(48)) + "\n",
    encoding="utf-8",
)
(root / "admin_password").write_text(
    existing_or_random("EXISTING_ADMIN_PASSWORD", lambda: secrets.token_urlsafe(24)) + "\n",
    encoding="utf-8",
)
fernet_key = existing_or_random(
    "EXISTING_ENCRYPTION_KEY",
    lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
)
(root / "encryption_key").write_text(fernet_key + "\n", encoding="utf-8")
for file_name, env_name in (
    ("openai_api_key", "EXISTING_OPENAI_API_KEY"),
    ("polish_api_key", "EXISTING_POLISH_API_KEY"),
    ("enhance_api_key", "EXISTING_ENHANCE_API_KEY"),
    ("emotion_api_key", "EXISTING_EMOTION_API_KEY"),
    ("compression_api_key", "EXISTING_COMPRESSION_API_KEY"),
):
    (root / file_name).write_text(provider_value(env_name) + "\n", encoding="utf-8")
(root / "restic_password").write_text(
    existing_or_random("EXISTING_RESTIC_PASSWORD", lambda: secrets.token_urlsafe(36)) + "\n",
    encoding="utf-8",
)
PY

chmod 600 "$secrets_dir"/*

if [ "$(id -u)" = "0" ]; then
  chown "$runtime_uid:$runtime_gid" "$secrets_dir"
  for name in $secret_files; do
    [ "$name" = "postgres_password" ] || chown "$runtime_uid:$runtime_gid" "$secrets_dir/$name"
  done
  # postgres:16-alpine runs as uid/gid 70 after its entrypoint drops root.
  chown 70:70 "$secrets_dir/postgres_password"
elif [ "$(id -u)" != "$runtime_uid" ] || [ "$(id -g)" != "$runtime_gid" ]; then
  echo "Secrets created, but ownership does not match GANKAIGC_RUNTIME_UID/GID." >&2
  echo "Run as root once: chown -R $runtime_uid:$runtime_gid '$secrets_dir'" >&2
  echo "Then: chown 70:70 '$secrets_dir/postgres_password'" >&2
  exit 1
else
  echo "Secrets created. Before production start run:" >&2
  echo "  sudo chown 70:70 '$secrets_dir/postgres_password'" >&2
fi

runtime_env="$project_dir/.env.runtime"
if [ ! -e "$runtime_env" ]; then
  : > "$runtime_env"
  chmod 600 "$runtime_env"
  if [ "$(id -u)" = "0" ]; then
    chown "$runtime_uid:$runtime_gid" "$runtime_env"
  fi
fi

echo "Created service-scoped production secrets in $secrets_dir (values not printed)."
echo "Next: provision roles, then run the one-shot migrator."
