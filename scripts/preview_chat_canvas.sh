#!/usr/bin/env bash
# Build the opt-in UI locally. Never calls release/deploy scripts or a backend.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/joshu/development/flutter-mac/bin/flutter}"
command -v "$FLUTTER_BIN" >/dev/null 2>&1 || FLUTTER_BIN=flutter
PORT=8770
BACKGROUND=0
LABEL=com.codex.sobriety-chat-canvas-preview
DOMAIN="gui/$(id -u)"
CACHE_ROOT="$HOME/Library/Caches/$LABEL"
for argument in "$@"; do
  case "$argument" in
    --background) BACKGROUND=1 ;;
    --status) exec launchctl print "$DOMAIN/$LABEL" ;;
    --stop) exec launchctl bootout "$DOMAIN/$LABEL" ;;
    *[!0-9]*|'') echo 'Usage: preview_chat_canvas.sh [port] [--background | --status | --stop]'; exit 1 ;;
    *) PORT="$argument" ;;
  esac
done
if (( BACKGROUND )); then
  [[ "$(uname)" == Darwin ]] || { echo '--background requires macOS'; exit 1; }
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo 'This preview service is already loaded. Use --status, or --stop before rebuilding.'
    exit 1
  fi
fi
# Do not replace or terminate anything occupying this port.
python3 - "$PORT" <<'CHECK_PORT'
import socket, sys
port = int(sys.argv[1])
if not 1024 <= port <= 65535:
    raise SystemExit('Choose a port from 1024 through 65535.')
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1', port))
    except OSError as error:
        raise SystemExit(f'Port {port} is unavailable; existing services were not changed: {error}')
CHECK_PORT
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sc-chat-preview.XXXXXX")"
trap 'rm -rf "$BUILD_ROOT"' EXIT
mkdir -p "$BUILD_ROOT/mobile_app" "$BUILD_ROOT/output/prototype"
# Only Dart/web sources and assets; no native signing files, caches, or .env.
cp "$REPO_ROOT/mobile_app/pubspec.yaml" "$REPO_ROOT/mobile_app/pubspec.lock" "$BUILD_ROOT/mobile_app/"
for directory in lib assets web; do
  cp -R "$REPO_ROOT/mobile_app/$directory" "$BUILD_ROOT/mobile_app/"
done
# Inject a clearly labelled local reply fixture into the throwaway copy only.
cp "$REPO_ROOT/scripts/preview_chat_repository.dart" "$BUILD_ROOT/mobile_app/lib/preview_chat_repository.dart"
python3 - "$BUILD_ROOT/mobile_app/lib/main.dart" <<'FIXTURE'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = "import 'preview_chat_repository.dart';\n" + s
s = s.replace('overrides: [sharedPreferencesProvider.overrideWithValue(prefs)],',
    'overrides: [sharedPreferencesProvider.overrideWithValue(prefs), chatRepositoryProvider.overrideWithValue(PreviewChatRepository())],')
p.write_text(s)
FIXTURE
(
  cd "$BUILD_ROOT/mobile_app"
  "$FLUTTER_BIN" pub get --offline
  nice -n 10 "$FLUTTER_BIN" build web --release --no-pub \
    --dart-define=DAY_HOME=true --base-href /prototype/ --no-wasm-dry-run
)
cp -R "$BUILD_ROOT/mobile_app/build/web/." "$BUILD_ROOT/output/prototype/"
python3 - "$BUILD_ROOT/output/prototype" <<'PY'
from pathlib import Path
import re, sys
root = Path(sys.argv[1])
p = root / 'index.html'
s = p.read_text().replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="connect-src \'self\' https://www.gstatic.com https://fonts.gstatic.com;">')
s = re.sub(r'<footer id="carrier-compliance-footer">.*?</footer>', '<footer id="carrier-compliance-footer">Local design preview · Demo replies · No server connection</footer>', s, flags=re.S)
p.write_text(s)
p = root / 'flutter_bootstrap.js'
s = p.read_text()
s = s[:s.rfind('_flutter.loader.load(')] + '_flutter.loader.load({});\n'
p.write_text(s)
PY
if (( BACKGROUND )); then
  # launchd owns the process, so ending a Codex turn or closing the shell will
  # not stop it. This is session-only: no login item is installed.
  mkdir -p "$CACHE_ROOT/output"
  cp -R "$BUILD_ROOT/output/." "$CACHE_ROOT/output/"
  python3 - "$CACHE_ROOT" "$LABEL" "$PORT" "$(command -v python3)" <<'SERVICE'
from pathlib import Path
import plistlib, sys
root, label, port, python = sys.argv[1:]
root = Path(root)
job = {
    'Label': label,
    'ProgramArguments': [python, '-u', '-m', 'http.server', port,
                         '--bind', '127.0.0.1', '--directory', str(root / 'output')],
    'RunAtLoad': True,
    'KeepAlive': True,
    'ThrottleInterval': 10,
    'StandardOutPath': str(root / 'server.log'),
    'StandardErrorPath': str(root / 'server-error.log'),
}
with (root / 'preview.plist').open('wb') as stream:
    plistlib.dump(job, stream)
SERVICE
  launchctl bootstrap "$DOMAIN" "$CACHE_ROOT/preview.plist"
  python3 - "$PORT" <<'VERIFY'
import sys, time, urllib.request
url = f'http://127.0.0.1:{sys.argv[1]}/prototype/'
for attempt in range(20):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200 and b'flutter_bootstrap.js' in response.read():
                break
    except OSError:
        pass
    time.sleep(0.25)
else:
    raise SystemExit('Preview failed its HTTP check; inspect --status and the cache log files.')
VERIFY
  printf 'Preview: http://localhost:%s/prototype/\nRuns independently until logout/reboot or --stop. No login item installed.\nLogs and assets: %s\n' "$PORT" "$CACHE_ROOT"
else
  printf 'Preview: http://localhost:%s/prototype/\nForeground mode: keep this terminal open. Use --background on macOS for a preview that survives this shell.\nPress Ctrl-C to stop and remove the temporary build.\n' "$PORT"
  python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$BUILD_ROOT/output"
fi
