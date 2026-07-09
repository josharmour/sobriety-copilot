#!/bin/bash
set -o pipefail
cd /mnt/repos/sobriety-copilot
PY=finetune/.venv/bin/python3
log(){ echo "[gen $(date +%H:%M:%S)] $*"; }
log "generating SFT+DPO (final-model) answers"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_gen_answers.py --model /home/joshu/ft-runs/final-model --name ft-dpo || { log "FAIL dpo-gen $?"; exit 1; }
log "generating SFT-only (sft-merged) answers"
CUDA_VISIBLE_DEVICES=1 $PY scripts/ft_gen_answers.py --model /home/joshu/ft-runs/sft-merged --name ft-sft || { log "FAIL sft-gen $?"; exit 2; }
log "BOTH ANSWER SETS COMPLETE"
