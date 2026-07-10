#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FT-F2: Convert SFT LoRA adapter / Merged model to on-device format
for flutter_gemma 0.13.6 / LiteRT-LM / MediaPipe.

Two routes:
  Route A (LoRA):   Convert PEFT LoRA → MediaPipe TFLite FlatBuffer
  Route B (Full):   Convert merged HF model → .litertlm via litert_torch.export_hf

Author: Hermes Agent (deployment-spike)
Date:   2026-07-09
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SFT_LORA_DIR = Path("/mnt/repos/sobriety-copilot/finetune/runs/sft-01")
SFT_MERGED_DIR = Path("/home/joshu/ft-runs/sft-merged")
OUTPUT_DIR = Path("/home/joshu/ft-runs")
DEPLOY_DIR = Path("/mnt/repos/sobriety-copilot/finetune/deploy")
ADAPTER_CONFIG = SFT_LORA_DIR / "adapter_config.json"
ADAPTER_MODEL = SFT_LORA_DIR / "adapter_model.safetensors"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    print(f"[F2] {msg}")


# ── Route A: LoRA to MediaPipe FlatBuffer ──────────────────────────────────
def route_a_lora():
    """Convert PEFT LoRA adapter to MediaPipe-compatible TFLite FlatBuffer."""
    log("=" * 60)
    log("ROUTE A: SFT LoRA → MediaPipe TFLite FlatBuffer")
    log("=" * 60)

    if not ADAPTER_MODEL.exists():
        log("ERROR: adapter_model.safetensors not found")
        return False

    from safetensors.torch import load_file
    import torch

    # Load config
    with open(ADAPTER_CONFIG) as f:
        adapter_cfg = json.load(f)

    rank = adapter_cfg.get("r", 32)
    lora_alpha = adapter_cfg.get("lora_alpha", 64)
    scale = lora_alpha / rank
    log(f"LoRA rank={rank}, alpha={lora_alpha}, scale={scale:.4f}")

    # Load weights to inspect projections
    weights = load_file(str(ADAPTER_MODEL))
    projections = set()
    for key in weights:
        for part in key.split("."):
            if part.endswith("_proj"):
                projections.add(part)
    log(f"LoRA projections found: {sorted(projections)}")

    # ── Step 1: Attention LoRA via litert_torch ─────────────────────────────
    log("\n── Step 1: Attention LoRA to FlatBuffer ──")
    attention_success = False
    tflite_path = OUTPUT_DIR / "sft-lora-attention.tflite"

    try:
        from litert_torch.generative.layers import lora as lora_utils
        from litert_torch.generative.layers.model_config import (
            ModelConfig,
            NormalizationConfig,
            NormalizationType,
            TransformerBlockConfig,
            AttentionConfig,
            AttentionType,
            FeedForwardConfig,
            FeedForwardType,
            ActivationConfig,
            ActivationType,
            KVCacheUpdateStrategy,
        )

        # Tensor name pattern matching our PEFT adapter
        tensor_names = lora_utils.LoRATensorNames(
            attn_query_w_a=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.q_proj.lora_A.weight"
            ),
            attn_query_w_b=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.q_proj.lora_B.weight"
            ),
            attn_key_w_a=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.k_proj.lora_A.weight"
            ),
            attn_key_w_b=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.k_proj.lora_B.weight"
            ),
            attn_value_w_a=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.v_proj.lora_A.weight"
            ),
            attn_value_w_b=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.v_proj.lora_B.weight"
            ),
            attn_output_w_a=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.o_proj.lora_A.weight"
            ),
            attn_output_w_b=(
                "base_model.model.model.language_model.layers.{}"
                ".self_attn.o_proj.lora_B.weight"
            ),
        )

        # Gemma 4 E2B text config (from config.json text_config)
        head_dim = 256
        n_heads = 8
        n_kv_heads = 1
        hidden_size = 1536
        intermediate_size = 6144
        num_layers = 35
        vocab_size = 262144

        # Layer types: layers 4,9,14,19,24,29,34 are full_attention
        layer_types = [
            "full_attention" if i % 5 == 4 else "sliding_attention"
            for i in range(num_layers)
        ]

        def build_attn_config(attn_type_str):
            is_global = attn_type_str == "full_attention"
            return AttentionConfig(
                num_heads=n_heads,
                head_dim=head_dim,
                num_query_groups=n_kv_heads,
                rotary_base=1000000 if is_global else 10000,
                rotary_percentage=0.25,
                use_alibi=False,
                qkv_transpose_before_split=False,
                qkv_use_bias=False,
                qkv_fused_interleaved=False,
                output_proj_use_bias=False,
                enable_kv_cache=True,
                query_norm_config=NormalizationConfig(
                    type=NormalizationType.RMS_NORM,
                    enable_hlfb=False,
                    epsilon=1e-6,
                    zero_centered=True,
                    with_scale=True,
                    scale_shift=0.0,
                    group_num=None,
                    use_bias=False,
                ),
                key_norm_config=NormalizationConfig(
                    type=NormalizationType.RMS_NORM,
                    enable_hlfb=False,
                    epsilon=1e-6,
                    zero_centered=True,
                    with_scale=True,
                    scale_shift=0.0,
                    group_num=None,
                    use_bias=False,
                ),
                value_norm_config=NormalizationConfig(
                    type=NormalizationType.RMS_NORM,
                    enable_hlfb=False,
                    epsilon=1e-6,
                    zero_centered=True,
                    with_scale=True,
                    scale_shift=0.0,
                    group_num=None,
                    use_bias=False,
                ),
                relative_attention_num_buckets=0,
                relative_attention_max_distance=0,
                logit_softcap=30.0,
                attn_type=AttentionType.GLOBAL if is_global else AttentionType.LOCAL_SLIDING,
                sliding_window_size=None if is_global else 512,
                causal_mask_value=0.0,
                kvcache_update_strategy=KVCacheUpdateStrategy.PREPEND_LEFT,
            )

        block_configs = []
        for i in range(num_layers):
            attn_type_str = layer_types[i]
            block_configs.append(
                TransformerBlockConfig(
                    attn_config=build_attn_config(attn_type_str),
                    ff_config=FeedForwardConfig(
                        type=FeedForwardType.GATED,
                        activation=ActivationConfig(type=ActivationType.GELU_TANH),
                        intermediate_size=intermediate_size,
                        use_separate_gating=False,
                        use_bias=False,
                        pre_ff_norm_config=None,
                        post_ff_norm_config=None,
                    ),
                    pre_attention_norm_config=NormalizationConfig(
                        type=NormalizationType.RMS_NORM,
                        enable_hlfb=False,
                        epsilon=1e-6,
                        zero_centered=True,
                        with_scale=True,
                        scale_shift=0.0,
                        group_num=None,
                        use_bias=False,
                    ),
                    post_attention_norm_config=None,
                    parallel_residual=False,
                    relative_attention=False,
                    kv_cache_max_len=512 if attn_type_str == "sliding_attention" else 4096,
                )
            )

        config = ModelConfig(
            vocab_size=vocab_size,
            num_layers=num_layers,
            max_seq_len=4096,
            embedding_dim=hidden_size,
            block_configs=block_configs,
            final_norm_config=NormalizationConfig(
                type=NormalizationType.RMS_NORM,
                enable_hlfb=False,
                epsilon=1e-6,
                zero_centered=True,
                with_scale=True,
                scale_shift=0.0,
                group_num=None,
                use_bias=False,
            ),
            embedding_scale=1.0,
            embedding_use_bias=False,
            image_embedding=None,
            num_mm_tokens_per_image=None,
            lm_head_use_bias=False,
            lm_head_share_weight_with_embedding=True,
            dense_intermediate_size=intermediate_size,
            enable_hlfb=False,
            final_logit_softcap=30.0,
            build_rope=lambda dim, hd, nh, nkh: None,
            attention_patterns=None,
        )

        log("Loading LoRA from safetensors...")
        lora = lora_utils.LoRA.from_safetensors(
            str(ADAPTER_MODEL),
            scale=scale,
            config=config,
            lora_tensor_names=tensor_names,
        )
        log(f"Loaded: rank={lora.get_rank()}, {len(lora.adapters)} layers")

        log("Converting to TFLite FlatBuffer...")
        tflite_bytes = lora.to_tflite()
        log(f"FlatBuffer size: {len(tflite_bytes)} bytes")

        with open(tflite_path, "wb") as f:
            f.write(tflite_bytes)
        log(f"Saved: {tflite_path} ({tflite_path.stat().st_size} bytes)")
        attention_success = True

    except ImportError as e:
        log(f"SKIP — missing dependency: {e}")
    except Exception as e:
        log(f"FAILED: {e}")
        traceback.print_exc()

    # ── Step 2: Handle MLP LoRA (not supported by litert_torch LoRA module) ──
    log("\n── Step 2: MLP LoRA (merge-only) ──")
    mlp_has_lora = any("mlp" in k for k in weights)
    if mlp_has_lora:
        log(
            "MLP LoRA weights found (gate_proj, up_proj, down_proj). "
            "NOTE: litert_torch.lora.LoRAEntry only supports attention projections. "
            "MLP LoRA must be merged into the base model before conversion, "
            "or the litert_torch LoRA module must be extended."
        )
        mlp_tensors = {k: v for k, v in weights.items() if "mlp" in k}
        log(f"  MLP LoRA tensors: {len(mlp_tensors)}")
    else:
        log("No MLP LoRA weights — attention-only adapter ✓")

    return attention_success


# ── Route B: Full merged model → .litertlm ─────────────────────────────────
def route_b_full():
    """Convert the full merged HuggingFace model to .litertlm format."""
    log("\n" + "=" * 60)
    log("ROUTE B: Merged HF Model → .litertlm")
    log("=" * 60)

    if not SFT_MERGED_DIR.exists():
        log("ERROR: merged model dir not found")
        return False

    from litert_torch.generative.export_hf import export

    output_dir = OUTPUT_DIR / "litertlm-export"
    output_dir.mkdir(parents=True, exist_ok=True)

    log(f"Input:  {SFT_MERGED_DIR}")
    log(f"Output: {output_dir}")
    log("")

    # Check available memory / warn
    import psutil
    mem = psutil.virtual_memory()
    log(f"System memory: {mem.total / 1e9:.1f} GB total, "
        f"{mem.available / 1e9:.1f} GB available")
    if mem.available < 20e9:
        log(
            "WARNING: <20 GB RAM available. Full model export may OOM "
            "or be extremely slow on CPU. Recommend running on the Plex "
            "machine (10.0.0.100) with GPU."
        )

    # Attempt export with minimal settings
    log("\n── Attempting text-only export ──")
    try:
        export.export(
            model=str(SFT_MERGED_DIR),
            output_dir=str(output_dir),
            task="text_generation",
            keep_temporary_files=False,
            trust_remote_code=False,
            prefill_lengths=[8, 16],  # small prefill to reduce memory
            cache_length=128,
            quantization_recipe=None,  # no quantization for now
            enable_dynamic_shape=None,
            externalize_embedder=True,
            single_token_embedder=None,
            bundle_litert_lm=True,
            use_jinja_template=True,
            experimental_lightweight_conversion=False,
        )
        log("Export completed successfully")

        # List output files
        for f in output_dir.iterdir():
            log(f"  {f.name} ({f.stat().st_size / 1e6:.1f} MB)")
        return True

    except Exception as e:
        log(f"FAILED: {e}")
        traceback.print_exc()

        # Check if partial output exists
        if output_dir.exists():
            log("Partial output:")
            for f in output_dir.iterdir():
                log(f"  {f.name} ({f.stat().st_size if f.is_file() else 'dir'})")
        return False


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    log("FT-F2: SFT → On-Device Conversion Spike")
    log(f"Python: {sys.version}")
    log(f"CWD:    {os.getcwd()}")
    log("")

    # Route A
    a_ok = route_a_lora()

    # Route B — only attempt if enough memory
    b_ok = False
    import psutil
    if psutil.virtual_memory().available > 20e9:
        b_ok = route_b_full()
    else:
        log("\nRoute B skipped: <20 GB RAM available (need GPU box at 10.0.0.100)")

    # ── Summary ──────────────────────────────────────────────────────────
    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)

    artifacts = []

    if a_ok:
        tflite_path = OUTPUT_DIR / "sft-lora-attention.tflite"
        if tflite_path.exists():
            artifacts.append(
                f"  ✅ Route A: {tflite_path} "
                f"({tflite_path.stat().st_size / 1024:.1f} KB)"
            )
    else:
        artifacts.append("  ❌ Route A: Failed — see errors above")

    if b_ok:
        artifacts.append(
            "  ✅ Route B: Export completed — check "
            f"{OUTPUT_DIR / 'litertlm-export/'}"
        )
    else:
        artifacts.append(
            "  ❌ Route B: Failed or skipped — see errors above"
        )

    for a in artifacts:
        log(a)

    log("")
    log("Deliverables:")
    log(f"  Report:  {DEPLOY_DIR / 'f2_report.md'}")
    log(f"  Script:  {Path(__file__).resolve()}")
    log(f"  LoRA:    {OUTPUT_DIR / 'sft-lora-attention.tflite'}")

    return 0 if (a_ok or b_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
