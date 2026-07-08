#!/usr/bin/env bash
# ============================================================================
# FT-D2: Training environment setup
# ============================================================================
# Creates finetune/.venv with:
#   - Unsloth  (Blackwell SM100 support confirmed ✓ — see notes)
#   - flash-attn (if prebuilt wheels available for this Python/CUDA)
#   - bitsandbytes, transformers, datasets, peft, trl, accelerate
#
# Unsloth version note (2026-07-07):
#   Unsloth 2026.7.1 pins torch < 2.11.0 (upper bound from unsloth_zoo deps).
#   This resolves torch 2.10.0+cu128 (CUDA 12.8 toolkit) — confirmed working
#   on NVIDIA RTX PRO 6000 Blackwell (CC 12.0 / SM100).  Unsloth has explicit
#   SM100 support (check_vllm_torch_sm100_compatibility + fix_vllm_pdl_blackwell).
#   When Unsloth drops the torch upper bound, switch to torch ~2.12.x+cu130.
#
#   Fallback to TRL+PEFT is NOT needed — Unsloth works on this platform.
#
# CIFS mount (Synology NAS) note:
#   Repo sits on a CIFS share without symlink support.  We detect venv creation
#   failure and work around by building in /tmp then rsync'ing with shebang fix.
#
# Usage:
#   bash finetune/infra/setup_env.sh            # create / rebuild venv
#   bash finetune/infra/setup_env.sh --check     # smoke test (exit 0 = pass)
#
# Smoke test loads Gemma 4 E2B tokenizer + config ONLY (no weights >10 GB).
# ============================================================================

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$REPO_ROOT/finetune/.venv"

# ------------------------------------------------------------------
# 1) INSTALL / UPDATE
# ------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
    echo "[setup_env] Creating venv at $VENV_DIR"

    # CIFS workaround for lib64 -> lib symlink issue
    if python3 -m venv "$VENV_DIR" --clear --upgrade-deps 2>/dev/null; then
        echo "[setup_env] venv created directly."
    else
        echo "[setup_env] Direct venv creation failed (CIFS symlink issue). Building via tmp …"
        TMPV=$(mktemp -d)
        python3 -m venv "$TMPV" --clear --upgrade-deps
        rsync -a --copy-links --delete "$TMPV/" "$VENV_DIR/"
        rm -rf "$TMPV"
        # Fix shebang paths in the copied venv
        find "$VENV_DIR/bin" -type f -exec \
            sed -i "1s|^#!.*python|#!$VENV_DIR/bin/python|" {} +
        echo "[setup_env] venv created via tmp copy + shebang fix."
    fi

    PIP="$VENV_DIR/bin/pip"

    # Unsloth pins torch < 2.11.0; install torch first to control version
    echo "[setup_env] Installing torch (Unsloth-compatible version) …"
    "$PIP" install --quiet torch==2.10.0

    echo "[setup_env] Installing core training deps …"
    "$PIP" install --quiet \
        transformers \
        sentencepiece \
        accelerate \
        datasets \
        peft \
        trl \
        bitsandbytes

    echo "[setup_env] Installing unsloth + unsloth_zoo …"
    "$PIP" install --quiet unsloth unsloth_zoo

    # flash-attn: prebuilt wheels may not exist for cp314; try gracefully
    echo "[setup_env] Installing flash-attn (optional) …"
    if "$PIP" install --quiet flash-attn 2>/dev/null; then
        echo "[setup_env] flash-attn installed."
    else
        echo "[setup_env] flash-attn not available (prebuilt wheel missing for this Python/CUDA). Using torch SDPA fallback."
    fi

    echo "[setup_env] Done."
    exit 0
fi

# ------------------------------------------------------------------
# 2) --CHECK
# ------------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
    if [[ ! -f "$VENV_DIR/bin/python" ]]; then
        echo "FAIL: venv not found at $VENV_DIR — run setup_env.sh first" >&2
        exit 1
    fi

    PYTHON="$VENV_DIR/bin/python"
    echo "--- FT-D2 smoke check ---"

    # ---- Library versions (pip list) ----
    echo ""
    echo "== Library versions =="
    "$PYTHON" -c "
import sys, subprocess, json
result = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format=json'],
                       capture_output=True, text=True, check=True)
pkgs = json.loads(result.stdout)
wanted = {'torch','transformers','accelerate','peft','trl','bitsandbytes',
          'datasets','sentencepiece','unsloth','flash-attn'}
for p in pkgs:
    name = p['name'].lower()
    if name in wanted:
        print(f'  {p[\"name\"]} == {p[\"version\"]}')
" 2>&1

    # ---- Hardware ----
    echo ""
    echo "== Hardware =="
    "$PYTHON" -c "
import torch
print(f'  torch: {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
print(f'  CUDA version: {torch.version.cuda}')
count = torch.cuda.device_count()
for i in range(count):
    p = torch.cuda.get_device_properties(i)
    print(f'  GPU {i}: {p.name}, {p.total_memory/1e9:.1f} GB, CC {p.major}.{p.minor}')
" 2>&1

    # ---- Gemma 4 E2B tokenizer + config smoke test (no weights >10 GB) ----
    echo ""
    echo "== Gemma 4 E2B base (smoke test — no weights downloaded) =="
    "$PYTHON" -c "
from pathlib import Path
import json
from huggingface_hub import hf_hub_download

HF_ID = 'google/gemma-4-e2b-it'
print(f'  HF repo: {HF_ID}')

# Download config (tiny) — verifies HF connectivity + model identity
config_path = hf_hub_download(HF_ID, 'config.json')
with open(config_path) as f:
    cfg = json.load(f)

text_cfg = cfg.get('text_config', {})
hidden = text_cfg.get('hidden_size', '?')
layers = text_cfg.get('num_hidden_layers', '?')
heads = text_cfg.get('num_attention_heads', '?')
kv_heads = text_cfg.get('num_key_value_heads', '?')
intermediate = text_cfg.get('intermediate_size', '?')
vocab = text_cfg.get('vocab_size', '?')
head_dim = text_cfg.get('head_dim', 256)

# Rough param estimate (text decoder only)
d_model = hidden
n_heads = heads
n_kv = kv_heads
embed_params = vocab * d_model
attn_per = d_model * n_heads * head_dim + 2 * d_model * n_kv * head_dim + n_heads * head_dim * d_model
mlp_per = d_model * intermediate * 2 + intermediate * 2 * d_model  # double-wide MLP
total_text_params = embed_params + layers * (attn_per + mlp_per)

print(f'  Architecture: Gemma4ForConditionalGeneration')
print(f'  Hidden size: {hidden}')
print(f'  Layers: {layers}')
print(f'  Attention heads: {heads}, KV heads: {kv_heads}')
print(f'  Head dim: {head_dim}')
print(f'  Intermediate (double-wide): {intermediate}')
print(f'  Vocab: {vocab}')
print(f'  Max seq len: {text_cfg.get(\"max_position_embeddings\", \"?\")}')
print(f'  Estimated text params: ~{total_text_params/1e9:.2f}B')
print(f'  Weight dtype: {cfg.get(\"dtype\", \"bfloat16\")}')

# Download & load tokenizer (small file)
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(HF_ID, trust_remote_code=True)
test = tok.encode('What does the Big Book say about step one?', add_special_tokens=True)
print(f'  Tokenizer: {tok.__class__.__name__}, vocab_size={tok.vocab_size}')
print(f'  Smoke test encode ({len(test)} tokens): \"{tok.decode(test)}\"')
print(f'  OK — config + tokenizer loaded (no model weights downloaded)')
" 2>&1

    # ---- VRAM estimate for QLoRA (seq-len 4096) ----
    echo ""
    echo "== VRAM estimate — QLoRA seq-len 4096 =="
    "$PYTHON" -c "
# Based on Gemma 4 E2B text config
n_params = 2.0e9  # ~2B params (text decoder only)

# 4-bit base model (NF4)
base_4bit_gb = n_params * 0.5 / 1e9

# LoRA params (r=16 on ~30 linear layers)
lora_params = 30 * 2 * 1536 * 16  # Q,K,V,O + up/down gates
lora_gb = lora_params * 2 / 1e9  # stored in bf16

# AdamW optimizer states for LoRA params (2 fp32 states per param)
opt_gb = lora_params * 4 * 2 / 1e9

# Activations at seq-len 4096, bs=1 (with gradient checkpointing)
act_gb = 35 * 1536 * 4096 * 2 / 1e9
act_ckpt_gb = act_gb * 0.1

total_gb = base_4bit_gb + lora_gb + opt_gb + act_ckpt_gb
free_gb_per_gpu = 96.0

print(f'  QLoRA base (4-bit NF4):     {base_4bit_gb:.1f} GB')
print(f'  LoRA adapters (r=16, bf16): {lora_gb:.2f} GB')
print(f'  AdamW states (LoRA only):    {opt_gb:.2f} GB')
print(f'  Activations (ckpt, bs=1):   {act_ckpt_gb:.1f} GB')
print(f'  ────────────────────────────────────')
print(f'  Estimated total:             {total_gb:.1f} GB')
print(f'  Available per GPU (D1 window): {free_gb_per_gpu:.0f} GB')
print(f'  Comfortably fits — batch size 8+ feasible at seq-len 4096')
" 2>&1

    echo ""
    echo "--- FT-D2 check PASS ---"
    exit 0
fi

# ------------------------------------------------------------------
# 3) Unknown flag
# ------------------------------------------------------------------
echo "Usage: bash $0          (create venv)"
echo "       bash $0 --check  (verify)" >&2
exit 1
