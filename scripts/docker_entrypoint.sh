#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "[entrypoint] starting: $*"

# 1) DB migrations（幂等，可关闭）
if [[ "${SKIP_DB_MIGRATIONS:-0}" != "1" ]]; then
  echo "[entrypoint] ensuring postgres migrations..."
  python -m scripts.init_db
else
  echo "[entrypoint] SKIP_DB_MIGRATIONS=1"
fi

# 2) Redis Streams & group init（幂等，可关闭）
if [[ "${SKIP_REDIS_STREAMS_INIT:-0}" != "1" ]]; then
  echo "[entrypoint] ensuring redis streams/groups..."
  python -m scripts.init_streams
else
  echo "[entrypoint] SKIP_REDIS_STREAMS_INIT=1"
fi

echo "[entrypoint] exec: $*"
exec "$@"
