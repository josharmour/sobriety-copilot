#!/bin/bash
# D-track driver — writes ALL model artifacts to LOCAL disk (/home/joshu/ft-runs);
# /mnt/repos is a CIFS mount to the NAS and 10GB writes stall there.
# Reads the SFT adapter from CIFS (small) but writes merged/DPO local.
set -o pipefail
cd /mnt/repos/sobriety-copilot
PY=finetune/.venv/bin/python3
LR=/home/joshu/ft-runs
log(){ echo "[dtrack $(date +%H:%M:%S)] $*"; }

log "STAGE 1: merge SFT adapter -> $LR/sft-merged (LOCAL)"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_merge_adapter.py \
    --adapter finetune/runs/sft-01 --out "$LR/sft-merged" || { log "FAIL: SFT merge (exit $?)"; exit 2; }
log "SFT merge done ($(du -sh $LR/sft-merged 2>/dev/null | cut -f1))"

log "STAGE 2: DPO dry-run (20 steps) -> $LR/dpo-dry (LOCAL)"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_train_dpo.py \
    --dataset finetune/gen/dpo.jsonl --adapter "$LR/sft-merged" \
    --max-steps 20 --output-dir "$LR/dpo-dry" || { log "FAIL: DPO dry-run (exit $?)"; exit 3; }
log "DPO DRY-RUN COMPLETE — gate for Fable to verify before full DPO"
