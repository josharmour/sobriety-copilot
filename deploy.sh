#!/bin/bash
set -e

NAS_HOST="${NAS_HOST:-10.0.0.100}"
REMOTE_DIR="/home/joshu/docker-stack/sobriety-copilot"

# Sync directories
echo "=== 1. Syncing source files to $NAS_HOST:$REMOTE_DIR ==="
ssh joshu@$NAS_HOST "mkdir -p $REMOTE_DIR/scratch/deploy_temp"
COPYFILE_DISABLE=1 tar --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' --exclude='._*' -cf - src static nginx docker-compose.yml Dockerfile requirements.txt .env | ssh joshu@$NAS_HOST "tar -C $REMOTE_DIR/scratch/deploy_temp -xf -"
ssh joshu@$NAS_HOST "cp -R $REMOTE_DIR/scratch/deploy_temp/* $REMOTE_DIR/ && rm -rf $REMOTE_DIR/scratch/deploy_temp"

# Rebuild and run
echo "=== 2. Rebuilding and restarting containers on Synology NAS ==="
ssh joshu@$NAS_HOST "export PATH=\$PATH:/usr/local/bin && cd $REMOTE_DIR && docker compose build app nginx && docker compose up -d"

echo "=== 3. NAS Deployment Complete! ==="
