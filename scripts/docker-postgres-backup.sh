#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-ai_polish}"
POSTGRES_USER="${POSTGRES_USER:-ai_polish}"

run_backup() {
  timestamp="$(date +%Y%m%d_%H%M%S)"
  dump_file="${BACKUP_DIR}/gankaigc_${POSTGRES_DB}_${timestamp}.dump"

  mkdir -p "$BACKUP_DIR"
  echo "[$(date -Iseconds)] creating backup: $dump_file"
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    --format=custom \
    --file="$dump_file" \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB"

  find "$BACKUP_DIR" -name "gankaigc_${POSTGRES_DB}_*.dump" -type f -mtime "+$BACKUP_RETENTION_DAYS" -delete
  echo "[$(date -Iseconds)] backup complete"
}

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "POSTGRES_PASSWORD is required" >&2
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
