#!/usr/bin/env sh
set -eu

project_dir="${GANKAIGC_HOST_PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
cd "$project_dir"

exec docker compose \
  --env-file .env.docker \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  --profile bootstrap \
  run --rm provision-roles
