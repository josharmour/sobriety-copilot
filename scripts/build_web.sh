#!/usr/bin/env bash
# scripts/build_web.sh
# Rebuild the website bundle (static/) from mobile_app/.
#
# Run it straight from the NAS repo. Flutter can't build on the SMB share, so
# this builds in a throwaway local copy (deleted on exit) and copies the result
# back into static/. Bump mobile_app/pubspec.yaml `version:` first so the served
# version.json tells this build apart from the live one. Commit static/ and run
# ./deploy.sh afterwards.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/joshu/development/flutter-mac/bin/flutter}"
command -v "$FLUTTER_BIN" >/dev/null 2>&1 || FLUTTER_BIN=flutter

BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sc-web-build.XXXXXX")"
trap 'rm -rf "$BUILD_ROOT"' EXIT

rsync -a --exclude build --exclude .dart_tool --exclude ios/Pods --exclude '._*' \
  --exclude .symlinks --exclude ephemeral --exclude .gradle \
  "$REPO_ROOT/mobile_app/" "$BUILD_ROOT/mobile_app/"
(cd "$BUILD_ROOT/mobile_app" && "$FLUTTER_BIN" build web --release)

# No --delete: keeps the hand-maintained pages in static/ (privacy.html,
# terms.html, sms-optin.html). -rlt, not -a/cp -R: the SMB share rejects
# copied permissions and macOS extended attributes.
rsync -rlt "$BUILD_ROOT/mobile_app/build/web/" "$REPO_ROOT/static/"
echo "==> static/ updated: $(cat "$REPO_ROOT/static/version.json")"
