#!/bin/bash
set -e

NAS_HOST="${NAS_HOST:-litellm}"
REMOTE_DIR="/home/joshu/docker-stack/sobriety-copilot"

# Sync directories
echo "=== 1. Syncing source files to $NAS_HOST:$REMOTE_DIR ==="
ssh $NAS_HOST "mkdir -p $REMOTE_DIR/scratch/deploy_temp $REMOTE_DIR/documents"
COPYFILE_DISABLE=1 tar --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' --exclude='._*' --exclude='.env' -cf - src static nginx docker-compose.yml Dockerfile requirements.txt documents/.manifests | ssh $NAS_HOST "tar -C $REMOTE_DIR/scratch/deploy_temp -xf -"
ssh $NAS_HOST "cp -R $REMOTE_DIR/scratch/deploy_temp/* $REMOTE_DIR/ && rm -rf $REMOTE_DIR/scratch/deploy_temp"
ssh $NAS_HOST "chmod -R a+rX $REMOTE_DIR/static $REMOTE_DIR/src $REMOTE_DIR/documents/.manifests"

# Rebuild and run
echo "=== 2. Rebuilding and restarting containers on server ==="
ssh $NAS_HOST "export PATH=\$PATH:/usr/local/bin && cd $REMOTE_DIR && docker compose build app nginx && docker compose up -d --force-recreate --no-deps app nginx worker"

echo "=== 3. Deployment Complete! ==="
