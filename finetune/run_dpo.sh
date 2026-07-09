#!/bin/bash
set -o pipefail
cd /mnt/repos/sobriety-copilot
PY=finetune/.venv/bin/python3
LR=/home/joshu/ft-runs
log(){ echo "[dpo $(date +%H:%M:%S)] $*"; }
log "DPO dry-run (20 steps) -> $LR/dpo-dry"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_train_dpo.py --dataset finetune/gen/dpo.jsonl \
   --adapter "$LR/sft-merged" --max-steps 20 --output-dir "$LR/dpo-dry" || { log "FAIL dry (exit $?)"; exit 1; }
log "DPO DRY-RUN COMPLETE"
