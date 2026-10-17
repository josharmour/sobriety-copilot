#!/usr/bin/env bash
# scripts/release_mobile.sh
# Fully automated release script for Sobriety Copilot Mobile.
# Builds and uploads iOS directly to TestFlight & App Store Connect,
# builds the signed Android App Bundle (AAB) for Google Play,
# bumps the build number, syncs Xcode targets, and pushes to GitHub.
#
# Run it straight from the NAS repo — never from a separate clone. Flutter and
# Xcode can't build on the SMB share (no POSIX byte-range locks), so the build
# itself happens in a throwaway local copy that is deleted on exit; version
# bumps are made, committed and pushed in the NAS repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOBILE_DIR="$REPO_ROOT/mobile_app"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/joshu/development/flutter-mac/bin/flutter}"

if [ ! -x "$FLUTTER_BIN" ]; then
  if command -v flutter >/dev/null 2>&1; then
    FLUTTER_BIN="flutter"
  else
    echo "ERROR: Flutter SDK not found at $FLUTTER_BIN or on PATH."
    exit 1
  fi
fi

# Parse options
BUMP_BUILD=true
NEW_VERSION=""
SKIP_IOS=false
SKIP_ANDROID=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-bump)
      BUMP_BUILD=false
      shift
      ;;
    --version)
      NEW_VERSION="$2"
      shift 2
      ;;
    --skip-ios)
      SKIP_IOS=true
      shift
      ;;
    --skip-android)
      SKIP_ANDROID=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--no-bump] [--version <x.y.z>] [--skip-ios] [--skip-android]"
      exit 1
      ;;
  esac
done

cd "$MOBILE_DIR"

# 1. Read current version and optionally bump
CURRENT_VERSION_LINE=$(grep '^version:' pubspec.yaml | head -n1)
CURRENT_VERSION_FULL=$(echo "$CURRENT_VERSION_LINE" | awk '{print $2}' | tr -d '"')
MARKETING_VERSION="${CURRENT_VERSION_FULL%+*}"
BUILD_NUMBER="${CURRENT_VERSION_FULL#*+}"

if [ -n "$NEW_VERSION" ]; then
  MARKETING_VERSION="$NEW_VERSION"
fi

if [ "$BUMP_BUILD" = true ]; then
  BUILD_NUMBER=$((BUILD_NUMBER + 1))
  NEW_FULL_VERSION="${MARKETING_VERSION}+${BUILD_NUMBER}"
  echo "==> Bumping version: ${CURRENT_VERSION_FULL} -> ${NEW_FULL_VERSION}"
  python3 -c "
import re
with open('pubspec.yaml', 'r') as f:
    content = f.read()
new_content = re.sub(r'^version:\s*.*$', 'version: ${NEW_FULL_VERSION}', content, flags=re.MULTILINE)
with open('pubspec.yaml', 'w') as f:
    f.write(new_content)
"
else
  NEW_FULL_VERSION="${MARKETING_VERSION}+${BUILD_NUMBER}"
  echo "==> Using existing version: ${NEW_FULL_VERSION}"
fi

# 2. Sync Xcode versioning
echo "==> Syncing Xcode targets..."
(cd ios && ruby sync_versions.rb)

# 3. Throwaway local build copy (working tree, so signing keys come along)
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sc-mobile-build.XXXXXX")"
trap 'rm -rf "$BUILD_ROOT"' EXIT
echo "==> Copying mobile_app to $BUILD_ROOT for the build..."
rsync -a --exclude build --exclude .dart_tool --exclude ios/Pods --exclude '._*' \
  --exclude .symlinks --exclude ephemeral --exclude .gradle \
  "$MOBILE_DIR/" "$BUILD_ROOT/mobile_app/"
cd "$BUILD_ROOT/mobile_app"

echo "==> Running flutter pub get..."
"$FLUTTER_BIN" pub get

# 4. iOS Build & TestFlight Upload
if [ "$SKIP_IOS" = false ]; then
  echo "==> [iOS] Building archive..."
  "$FLUTTER_BIN" build ipa --export-options-plist=ios/ExportOptions-upload.plist

  echo "==> [iOS] Uploading to App Store Connect / TestFlight..."
  xcodebuild -exportArchive \
    -archivePath build/ios/archive/Runner.xcarchive \
    -exportPath /tmp/xcode-upload \
    -exportOptionsPlist ios/ExportOptions-upload.plist \
    -allowProvisioningUpdates
  echo "==> [iOS] Successfully uploaded build ${NEW_FULL_VERSION} to TestFlight!"
fi

# 5. Android Build
if [ "$SKIP_ANDROID" = false ]; then
  echo "==> [Android] Building signed release App Bundle (AAB)..."
  "$FLUTTER_BIN" build appbundle --release
  AAB_PATH="$MOBILE_DIR/build/app/outputs/bundle/release/app-release.aab"
  mkdir -p "$(dirname "$AAB_PATH")"
  # cat, not cp: macOS cp copies extended attributes, which SMB rejects.
  cat build/app/outputs/bundle/release/app-release.aab > "$AAB_PATH"
  echo "==> [Android] Successfully built: $AAB_PATH"

  # Check if Google Play API credentials exist
  PLAY_CREDS="${PLAY_STORE_JSON:-$MOBILE_DIR/android/play-service-account.json}"
  if [ -f "$PLAY_CREDS" ]; then
    echo "==> [Android] Uploading AAB to Google Play via service account..."
    if command -v fastlane >/dev/null 2>&1; then
      fastlane supply --aab "$AAB_PATH" --json_key "$PLAY_CREDS" --package_name "com.sobrietycopilot.app" --track "production"
    fi
  else
    echo "==> [Android] Play Store service account not found at $PLAY_CREDS."
    echo "    To upload: Open Google Play Console -> Production -> Upload: $AAB_PATH"
  fi
fi

# 6. Commit and push version bump (in the NAS repo; fsmonitor hangs on SMB)
echo "==> Committing and pushing version ${NEW_FULL_VERSION}..."
cd "$MOBILE_DIR"
GIT="git -c core.fsmonitor=false"
$GIT add pubspec.yaml ios/Runner.xcodeproj/project.pbxproj ios/sync_versions.rb
$GIT commit -m "chore(release): bump mobile app to ${NEW_FULL_VERSION}" || true
$GIT push origin "$($GIT rev-parse --abbrev-ref HEAD)" || true

echo ""
echo "=========================================================="
echo " ✅ Mobile Release ${NEW_FULL_VERSION} Complete!"
echo " - iOS: Uploaded to TestFlight & available for App Store"
echo " - Android: Signed AAB ready at $MOBILE_DIR/build/app/outputs/bundle/release/app-release.aab"
echo "=========================================================="
