#!/bin/bash
set -e

cd /Volumes/repos/sobriety-copilot

echo "=== Testing connectivity to blackwell (10.0.0.10) and litellm (10.0.0.100) ==="
TARGET_HOST=""

if ssh -o BatchMode=yes -o ConnectTimeout=3 joshu@10.0.0.10 "echo ping" >/dev/null 2>&1; then
    TARGET_HOST="10.0.0.10"
    echo "Found active server at 10.0.0.10 (blackwell)"
elif ssh -o BatchMode=yes -o ConnectTimeout=3 joshu@10.0.0.100 "echo ping" >/dev/null 2>&1; then
    TARGET_HOST="10.0.0.100"
    echo "Found active server at 10.0.0.100 (litellm)"
else
    echo "ERROR: Could not connect to 10.0.0.10 or 10.0.0.100 via SSH."
    read -p "Press Enter to exit..."
    exit 1
fi

export NAS_HOST="$TARGET_HOST"
echo "Deploying to $NAS_HOST..."
./deploy.sh

echo ""
echo "=== Deployment to $TARGET_HOST finished successfully! ==="
read -p "Press Enter to close this window..."
