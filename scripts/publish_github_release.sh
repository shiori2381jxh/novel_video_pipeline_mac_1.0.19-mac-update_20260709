#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RELEASE_REPO="${RELEASE_REPO:-shiori2381jxh/novel_video_pipeline_mac_1.0.19-mac-update_20260709}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v gh >/dev/null 2>&1; then
  echo "[ERROR] GitHub CLI not found. Install it first: brew install gh"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "[ERROR] GitHub CLI is not logged in. Run: gh auth login"
  exit 1
fi

VERSION="$("$PYTHON_BIN" - <<'PY'
from app.version import VERSION
print(VERSION)
PY
)"
TAG="v${VERSION}"
NOTES_FILE="${NOTES_FILE:-}"

BUILD_ARGS=(scripts/build_release_package.py --platform all --repo "$RELEASE_REPO")
if [ -n "$NOTES_FILE" ]; then
  BUILD_ARGS+=(--notes-file "$NOTES_FILE")
fi

"$PYTHON_BIN" "${BUILD_ARGS[@]}"

MAC_ZIP="$(ls -t dist/novel_video_pipeline_mac_"${VERSION//[^A-Za-z0-9._-]/_}"_*.zip | head -n 1)"
WINDOWS_ZIP="$(ls -t dist/novel_video_pipeline_windows_"${VERSION//[^A-Za-z0-9._-]/_}"_*.zip | head -n 1)"
ASSETS=("$MAC_ZIP" "$WINDOWS_ZIP" "dist/latest.json" "dist/latest-windows.json")

if gh release view "$TAG" --repo "$RELEASE_REPO" >/dev/null 2>&1; then
  echo "[release] ${TAG} exists, uploading assets with --clobber"
  gh release upload "$TAG" "${ASSETS[@]}" --repo "$RELEASE_REPO" --clobber
else
  echo "[release] creating ${TAG} in ${RELEASE_REPO}"
  if [ -n "$NOTES_FILE" ] && [ -f "$NOTES_FILE" ]; then
    gh release create "$TAG" "${ASSETS[@]}" --repo "$RELEASE_REPO" --title "Novel Video Pipeline ${VERSION} (macOS + Windows)" --notes-file "$NOTES_FILE"
  else
    gh release create "$TAG" "${ASSETS[@]}" --repo "$RELEASE_REPO" --title "Novel Video Pipeline ${VERSION} (macOS + Windows)" --notes "Novel Video Pipeline ${VERSION}, built for macOS and Windows from the same commit."
  fi
fi

echo "[ok] Release assets uploaded:"
printf '  %s\n' "${ASSETS[@]}"
echo "Manifest URL:"
echo "  https://github.com/${RELEASE_REPO}/releases/latest/download/latest.json"
echo "  https://github.com/${RELEASE_REPO}/releases/latest/download/latest-windows.json"
