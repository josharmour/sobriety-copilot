#!/bin/bash
set -e

# Sync directories
echo "=== 1. Syncing source files to Synology NAS (10.0.0.2) ==="
ssh joshu@10.0.0.2 'rm -rf /volume1/repos/sobriety-copilot/scratch/deploy_temp && mkdir -p /volume1/repos/sobriety-copilot/scratch/deploy_temp'
tar --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' -cf - src static nginx docker-compose.yml Dockerfile requirements.txt .env | ssh joshu@10.0.0.2 'tar -C /volume1/repos/sobriety-copilot/scratch/deploy_temp -xf -'
ssh joshu@10.0.0.2 'cp -R /volume1/repos/sobriety-copilot/scratch/deploy_temp/* /volume1/repos/sobriety-copilot/ && rm -rf /volume1/repos/sobriety-copilot/scratch/deploy_temp'

# Rebuild and run
echo "=== 2. Rebuilding and restarting containers on Synology NAS ==="
ssh joshu@10.0.0.2 'export PATH=$PATH:/usr/local/bin && cd /volume1/repos/sobriety-copilot && docker-compose build app nginx && docker-compose up -d'

echo "=== 3. NAS Deployment Complete! ==="
