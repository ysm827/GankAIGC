#!/usr/bin/env sh
set -eu
umask 077

load_secret_file() {
  variable_name="$1"
  case "$variable_name" in
    POSTGRES_PASSWORD) file_path="${POSTGRES_PASSWORD_FILE:-}" ;;
    *) echo "unsupported secret variable" >&2; exit 1 ;;
  esac
  file_variable_name="${variable_name}_FILE"
  [ -n "$file_path" ] || return 0
  [ -f "$file_path" ] || {
    echo "$file_variable_name must point to a regular file" >&2
    exit 1
  }
  file_mode="$(stat -c '%a' "$file_path")"
  [ "$file_mode" = "600" ] || [ "$file_mode" = "400" ] || {
    echo "$file_variable_name must have mode 0600 or 0400" >&2
    exit 1
  }
  secret_value="$(cat "$file_path")"
  [ -n "$secret_value" ] || {
    echo "$file_variable_name is empty" >&2
    exit 1
  }
  export "$variable_name=$secret_value"
}

load_secret_file POSTGRES_PASSWORD

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-ai_polish}"
POSTGRES_USER="${POSTGRES_USER:-ai_polish}"
BACKUP_FILE_GID="${BACKUP_FILE_GID:-0}"

run_backup() {
  timestamp="$(date +%Y%m%d_%H%M%S)"
  dump_file="${BACKUP_DIR}/gankaigc_${POSTGRES_DB}_${timestamp}.dump"
  if [ -e "$dump_file" ]; then
    dump_file="${BACKUP_DIR}/gankaigc_${POSTGRES_DB}_${timestamp}_$$.dump"
  fi
  partial_file="${dump_file}.partial.$$"
  checksum_file="${dump_file}.sha256"
  checksum_partial="${checksum_file}.partial.$$"

  mkdir -p "$BACKUP_DIR"
  echo "[$(date -Iseconds)] creating backup: $(basename "$dump_file")"
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    --format=custom \
    --file="$partial_file" \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB"

  # A dump is not successful until PostgreSQL can parse its archive catalog.
  pg_restore --list "$partial_file" >/dev/null
  chown "0:${BACKUP_FILE_GID}" "$partial_file"
  chmod 640 "$partial_file"
  sync
  mv "$partial_file" "$dump_file"

  (cd "$BACKUP_DIR" && sha256sum "$(basename "$dump_file")") > "$checksum_partial"
  chown "0:${BACKUP_FILE_GID}" "$checksum_partial"
  chmod 640 "$checksum_partial"
  sync
  mv "$checksum_partial" "$checksum_file"
  sync

  find "$BACKUP_DIR" -name "gankaigc_${POSTGRES_DB}_*.dump" -type f -mtime "+$BACKUP_RETENTION_DAYS" -delete
  find "$BACKUP_DIR" -name "gankaigc_${POSTGRES_DB}_*.dump.sha256" -type f -mtime "+$BACKUP_RETENTION_DAYS" -delete
  find "$BACKUP_DIR" -name "gankaigc_${POSTGRES_DB}_*.partial.*" -type f -mtime +2 -delete
  echo "[$(date -Iseconds)] backup validated: $(basename "$dump_file")"
}

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "POSTGRES_PASSWORD or POSTGRES_PASSWORD_FILE is required" >&2
  exit 1
fi

if [ "${RUN_ONCE:-false}" = "true" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "$BACKUP_INTERVAL_SECONDS"
done
