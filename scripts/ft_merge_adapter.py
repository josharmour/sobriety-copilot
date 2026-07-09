#!/usr/bin/env python3
"""Merge a LoRA adapter into its base and save a standalone bf16 model.

Used twice in the D-track: after SFT (SFT adapter -> merged base for DPO) and
after DPO (DPO adapter -> final exportable model for D5/serving).

Usage:
  python scripts/ft_merge_adapter.py --adapter finetune/runs/sft-01 \
      --out finetune/runs/sft-01/merged
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="adapter dir (has adapter_config.json)")
    ap.add_argument("--out", required=True, help="output dir for the merged bf16 model")
    ap.add_argument("--max-seq", type=int, default=4096)
    args = ap.parse_args()

    from unsloth import FastLanguageModel
    import torch

    print(f"[merge] loading base+adapter: {args.adapter}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        args.adapter,
        max_seq_length=args.max_seq,
        dtype=torch.bfloat16,
        load_in_4bit=False,
    )
    print(f"[merge] saving merged bf16 -> {args.out}")
    model.save_pretrained_merged(args.out, tokenizer, save_method="merged_16bit")
    print("[merge] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
