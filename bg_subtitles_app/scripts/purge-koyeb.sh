#!/usr/bin/env bash
set -euo pipefail

# Remove unused services by ID. Usage:
#   scripts/purge-koyeb.sh <SERVICE_ID> [<SERVICE_ID>...]

if [[ $# = 0 ]]; then
  echo "Usage: $0 <SERVICE_ID> [<SERVICE_ID>...]" >&2
  exit 2
fi

for SVC in "$@"; do
  echo "→ Deleting service ${SVC}"
  koyeb services delete "${SVC}" || true
done

echo "→ Remaining services:"
koyeb services list

