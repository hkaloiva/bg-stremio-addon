#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/release.sh vX.Y.Z
# - Validates tag format
# - Bumps version in src/app.py MANIFEST and README badge
# - Creates a git commit and tag locally (does not push)

TAG=${1:-}
if [[ -z "$TAG" ]]; then
  echo "usage: $0 vX.Y.Z" >&2
  exit 2
fi

if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: tag must be semver like v0.2.0" >&2
  exit 2
fi

VERSION=${TAG#v}

echo "→ Bumping version to ${VERSION}"
python3 scripts/bump_version.py "${VERSION}"

echo "→ Creating commit"
git add src/app.py README.md || true
git commit -m "chore: release ${TAG}" || echo "(no changes to commit)"

echo "→ Tagging ${TAG}"
git tag -a "${TAG}" -m "Release ${TAG}" || {
  echo "(tag may already exist)"
}

cat <<EOF

Next steps:
  git push origin main --tags
  # Wait for GitHub Actions to publish Docker images
  # Promote to production:
  ./scripts/promote.sh ${TAG}
EOF

