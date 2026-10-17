#!/usr/bin/env bash
# Deploy the WORKING TREE as the public beta, https://beta.sobrietycopilot.com,
# beside production on the same host — production is not touched.
#
#   containers  beta-app + beta-nginx (compose project "sobriety-copilot-beta"), host port 5077
#   tunnel      Cloudflare route beta.sobrietycopilot.com -> http://10.0.0.100:5077
#   shares      production's chroma / redis / embed services (joins its network under
#               distinct service names, so prod nginx's "app" upstream never resolves here),
#               its documents (read-only) and its LLM settings (.env)
#   own data    volume beta_memory (user/bug/SMS DBs, caches); Twilio credentials blanked
#   web         built from mobile_app/ in a temp copy; the repo's static/ is not modified
#
# Remove:  ssh litellm 'cd ~/docker-stack/sobriety-copilot-beta && docker compose -p sobriety-copilot-beta down -v'
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/joshu/development/flutter-mac/bin/flutter}"
HOST="${BETA_HOST:-litellm}"
PORT="${BETA_PORT:-5077}"
REMOTE=/home/joshu/docker-stack/sobriety-copilot-beta
PROD=/home/joshu/docker-stack/sobriety-copilot
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sc-beta.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

if [[ "${SKIP_WEB:-0}" != "1" ]]; then
  echo "==> building web bundle"
  rsync -a --exclude build --exclude .dart_tool --exclude ios/Pods --exclude '._*' \
    --exclude .symlinks --exclude ephemeral --exclude .gradle "$REPO/mobile_app/" "$WORK/mobile_app/"
  (cd "$WORK/mobile_app" && "$FLUTTER_BIN" build web --release >/dev/null)
  WEB="$WORK/mobile_app/build/web"
else
  echo "==> SKIP_WEB=1: reusing the web bundle already on the server"
  WEB=""
fi

echo "==> assembling payload"
PAY="$WORK/payload"
mkdir -p "$PAY/static"
rsync -a --exclude __pycache__ "$REPO/src" "$PAY/"
cp "$REPO/Dockerfile" "$REPO/requirements.txt" "$PAY/"
rsync -a "$REPO/nginx" "$PAY/"
sed -i '' 's/app:5000/beta-app:5000/g' "$PAY/nginx/conf.d/default.conf"
if [[ -n "$WEB" ]]; then
  rsync -rlt "$REPO/static/" "$PAY/static/"   # hand-maintained pages (privacy, terms, sms-optin)
  rsync -rlt "$WEB/" "$PAY/static/"
fi

echo "==> copying to $HOST:$REMOTE"
ssh "$HOST" "mkdir -p $REMOTE/static"
if [[ -z "$WEB" ]]; then rmdir "$PAY/static"; fi
COPYFILE_DISABLE=1 tar -C "$PAY" -czf - . | ssh "$HOST" "tar -C $REMOTE -xzf - 2>/dev/null; chmod -R a+rX $REMOTE"

echo "==> writing compose and starting"
ssh "$HOST" "cd $REMOTE && PORT=$PORT PROD=$PROD python3 - <<'PY'
import json, os, subprocess
prod = os.environ['PROD']
cfg = json.loads(subprocess.check_output(
    ['docker', 'compose', '-f', f'{prod}/docker-compose.yml', '--env-file', f'{prod}/.env', 'config', '--format', 'json'],
    cwd=prod))
env = dict(cfg['services']['app']['environment'])
env.update({
    'USER_MEMORY_DB_PATH': '/home/app/memory/user_memory.db',
    'BUG_REPORT_DB_PATH': '/home/app/memory/bug_reports.db',
    'SMS_SUBSCRIPTIONS_DB_PATH': '/home/app/memory/sms_subscriptions.db',
    'TWILIO_ACCOUNT_SID': '', 'TWILIO_AUTH_TOKEN': '', 'TWILIO_MESSAGING_SERVICE_SID': '',
})
compose = {
    'name': 'sobriety-copilot-beta',
    'services': {
        'beta-app': {
            'build': '.', 'image': 'sobriety-copilot-beta-app', 'restart': 'unless-stopped',
            'environment': env, 'cpus': 2,
            'extra_hosts': ['host.docker.internal:host-gateway'],
            'volumes': [f'{prod}/documents:/app/documents:ro', f'{prod}/packs:/app/packs:ro',
                        'beta_memory:/home/app/memory', 'models_data:/app/models:ro'],
            'networks': ['prodnet'],
        },
        'beta-nginx': {
            'build': {'context': '.', 'dockerfile': 'nginx/Dockerfile'}, 'image': 'sobriety-copilot-beta-nginx',
            'restart': 'unless-stopped', 'ports': [f\"{os.environ['PORT']}:80\"],
            'networks': ['prodnet'], 'depends_on': ['beta-app'],
        },
    },
    'networks': {'prodnet': {'external': True, 'name': 'sobriety-copilot_default'}},
    'volumes': {'beta_memory': {}, 'models_data': {'external': True, 'name': 'sobriety-copilot_models_data'}},
}
json.dump(compose, open('docker-compose.yml', 'w'), indent=1)
PY
docker compose -p sobriety-copilot-beta build -q
docker compose -p sobriety-copilot-beta create
# Seed the BM25 cache so a fresh volume doesn't re-tokenize 178k chunks on start.
if ! docker run --rm -v sobriety-copilot-beta_beta_memory:/m alpine sh -c 'ls /m/bm25_cache_*.pkl' >/dev/null 2>&1; then
  for f in \$(docker exec sobriety-copilot-app-1 sh -c 'ls /home/app/memory/bm25_cache_recovery_literature_gemma_v1.pkl'); do
    docker cp sobriety-copilot-app-1:\$f /tmp/beta_bm25.pkl
    docker run --rm -v sobriety-copilot-beta_beta_memory:/m -v /tmp/beta_bm25.pkl:/src.pkl:ro alpine \
      sh -c 'cp /src.pkl /m/bm25_cache_recovery_literature_gemma_v1.pkl && chown 1000:1000 /m/*.pkl'
    rm -f /tmp/beta_bm25.pkl
  done
fi
docker compose -p sobriety-copilot-beta up -d --force-recreate
"
echo "==> beta starting: http://10.0.0.100:$PORT  ->  https://beta.sobrietycopilot.com"
