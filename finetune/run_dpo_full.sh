#!/bin/bash
set -o pipefail
cd /mnt/repos/sobriety-copilot
PY=finetune/.venv/bin/python3
LR=/home/joshu/ft-runs
log(){ echo "[dpofull $(date +%H:%M:%S)] $*"; }

log "STAGE A: full DPO (2 epochs) -> $LR/dpo-01"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_train_dpo.py --dataset finetune/gen/dpo.jsonl \
   --adapter "$LR/sft-merged" --num-epochs 2 --output-dir "$LR/dpo-01" || { log "FAIL: full DPO (exit $?)"; exit 1; }
log "DPO full done"

log "STAGE B: merge DPO adapter -> $LR/final-model"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_merge_adapter.py --adapter "$LR/dpo-01" --out "$LR/final-model" || { log "FAIL: DPO merge (exit $?)"; exit 2; }
log "FINAL MODEL READY at $LR/final-model"
