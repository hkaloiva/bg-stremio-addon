#!/usr/bin/env bash
set -euo pipefail

# Deploy to Koyeb using the koyeb CLI
# This script commits changes, pushes to GitHub, and deploys via Koyeb

echo "🚀 Deploying Toast Translator to Koyeb"
echo "======================================"
echo ""

# Check if koyeb CLI is installed
if ! command -v koyeb &> /dev/null; then
    echo "❌ koyeb CLI not found. Install with: npm install -g @koyeb/koyeb-cli"
    exit 1
fi

# Check if we're in git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not in a git repository"
    exit 1
fi

# Get service ID from argument or prompt
SERVICE_ID="${1:-}"
if [[ -z "${SERVICE_ID}" ]]; then
    echo "Please provide your Koyeb service ID:"
    echo "Example: toast-translator-kaloyan8907-8d1fe372"
    echo ""
    read -p "Service ID: " SERVICE_ID
fi

if [[ -z "${SERVICE_ID}" ]]; then
    echo "❌ Service ID is required"
    exit 1
fi

echo "📦 Checking for uncommitted changes..."
if [[ -n $(git status --porcelain) ]]; then
    echo "Found uncommitted changes. Committing..."
    git add -A
    git commit -m "Deploy: $(date '+%Y-%m-%d %H:%M:%S')" || true
fi

echo "⬆️  Pushing to GitHub..."
git push origin main || git push origin master

echo "☁️  Creating Koyeb archive..."
ARCHIVE_JSON=$(koyeb archives create . \
  --ignore-dir .git \
  --ignore-dir .venv \
  --ignore-dir node_modules \
  --ignore-dir __pycache__ \
  --ignore-dir cache \
  --ignore-dir tests \
  -o json)

ARCHIVE_ID=$(echo "${ARCHIVE_JSON}" | jq -r '.archive.id')
echo "✅ Archive created: ${ARCHIVE_ID}"

echo "🐳 Deploying with Docker builder..."
koyeb services update "${SERVICE_ID}" \
  --archive "${ARCHIVE_ID}" \
  --archive-builder docker \
  --docker Dockerfile.koyeb \
  -o json | jq -r '.latest_deployment_id'

echo ""
echo "✨ Deployment initiated!"
echo ""
echo "📊 Monitor deployment:"
echo "   koyeb service logs ${SERVICE_ID} --type build --tail"
echo ""
echo "🔄 If deployment fails due to registry issues, retry with:"
echo "   koyeb services redeploy ${SERVICE_ID} --use-cache --wait"
echo ""
