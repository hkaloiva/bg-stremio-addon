#!/usr/bin/env bash
set -euo pipefail

# Koyeb deploy helper with retries and dual builders (buildpack/docker).
# Usage:
#   scripts/deploy-koyeb.sh buildpack <SERVICE_ID>
#   scripts/deploy-koyeb.sh docker    <SERVICE_ID>

MODE=${1:-buildpack}
SERVICE=${2:-}

if [[ -z "${SERVICE}" ]]; then
  echo "error: missing SERVICE_ID (arg 2)" >&2
  exit 2
fi

echo "→ Creating archive..."
ARCHIVE_JSON=$(koyeb archives create . \
  --ignore-dir .git \
  --ignore-dir .venv \
  --ignore-dir subsland-playwright-proxy/node_modules \
  -o json)
ARCHIVE_ID=$(jq -r '.archive.id' <<<"${ARCHIVE_JSON}")
echo "→ Archive: ${ARCHIVE_ID}"

if [[ "${MODE}" == "buildpack" ]]; then
  echo "→ Deploying with buildpack builder"
  koyeb services update "${SERVICE}" \
    --archive "${ARCHIVE_ID}" \
    --archive-builder buildpack \
    --archive-buildpack-build-command "pip install --no-cache-dir -r requirements.txt" \
    --archive-buildpack-run-command "uvicorn src.app:app --host 0.0.0.0 --port 8080" \
    --env PYTHONPATH=src \
    --env UVICORN_PORT=8080 \
    -o json | jq -r '.latest_deployment_id'
else
  echo "→ Deploying with docker builder"
  koyeb services update "${SERVICE}" \
    --archive "${ARCHIVE_ID}" \
    --archive-builder docker \
    -o json | jq -r '.latest_deployment_id'
fi

echo "→ Tailing build logs for a short window (Ctrl-C to stop)"
timeout 30s koyeb service logs "${SERVICE}" --type build --tail || true

echo "→ If deploy is marked degraded due to registry 500s, retry with:"
echo "   koyeb services redeploy ${SERVICE} --use-cache --wait"

