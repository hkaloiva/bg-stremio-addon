#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"

exec /usr/local/bin/gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b "0.0.0.0:${PORT}" --timeout 180 --graceful-timeout 30 --keep-alive 65 src.translator_app.main:app

