#!/usr/bin/env bash
set -euo pipefail

# Redeploy to Koyeb using a specific docker image

echo "🚀 Redeploying Toast Translator to Koyeb"
echo "======================================"
echo ""

# Check if koyeb CLI is installed
if ! command -v koyeb &> /dev/null; then
    echo "❌ koyeb CLI not found. Install with: npm install -g @koyeb/koyeb-cli"
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

echo " redeploying with Docker image..."
koyeb services update "${SERVICE_ID}" \
  --docker "greenbluegreen/toast-translator:v1.1.0-golden" \
  -o json | jq -r '.latest_deployment_id'

echo ""
echo "✨ Redeployment initiated!"
echo ""
echo "📊 Monitor deployment:"
echo "   koyeb service logs ${SERVICE_ID} --type build --tail"
echo ""
echo "🔄 If deployment fails, you can investigate further."
echo ""
