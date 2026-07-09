#!/usr/bin/env python3
"""FT-D3: SFT training script — QLoRA fine-tune on google/gemma-4-e2b-it.

Usage:
    # CPU-side validation (no GPU, no weight downloads):
    python scripts/ft_train_sft.py --dataset finetune/gen/sft.jsonl \\
        --dry-run 20

    # Full training (D1 window — GPU allocated to this process):
    python scripts/ft_train_sft.py --dataset finetune/gen/sft.jsonl \\
        --config finetune/infra/sft_config.yaml

    # Override config fields:
    python scripts/ft_train_sft.py --dataset ... \\
        --output-dir finetune/runs/sft-ablation --learning-rate 1e-4

Dataset schema (JSONL):
    {"messages":[{"role":"system","content":"..."},
                 {"role":"user","content":"..."},
                 {"role":"assistant","content":"..."}],
     "meta":{"intent_id":"...","difficulty":"...","register":"...",
             "crisis_adjacent":false,"sample_type":"context|refusal",
             "gold_blocks":[],"gold_docs":[],
             "distractor_blocks":[],"distractor_docs":[]}}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import math
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "finetune" / "infra" / "sft_config.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "finetune" / "runs" / "sft-01"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SFT QLoRA training for sobriety-copilot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dataset", required=True,
        help="Path to JSONL dataset (messages+meta format).",
    )
    p.add_argument(
        "--config", default=str(DEFAULT_CONFIG),
        help="Path to YAML config (default: %(default)s).",
    )
    p.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT),
        help="Output directory for checkpoints/metrics (default: %(default)s).",
    )
    p.add_argument(
        "--dry-run", nargs="?", const=20, type=int, default=0,
        metavar="N",
        help="CPU-side validation: check config, dataset, tokenizer, packing, "
             "and paths — no GPU, no model weights.  Default N=20 steps / "
             "200 samples.  Pass 0 to disable.",
    )
    # Overridable hyperparams (convenience so the D1-window run needs no YAML edit)
    p.add_argument("--learning-rate", type=float, default=None)
    p.add_argument("--num-epochs", type=float, default=None)
    p.add_argument("--per-device-train-batch-size", type=int, default=None)
    p.add_argument("--gradient-accumulation-steps", type=int, default=None)
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--lr-scheduler-type", default=None)
    p.add_argument("--warmup-ratio", type=float, default=None)
    p.add_argument("--seq-len", type=int, default=None,
                   help="Override sequence length (default: from config, 4096).")
    p.add_argument("--resume-from", type=str, default=None,
                   help="Path to checkpoint dir to resume from.")
    return p


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict[str, Any]:
    import yaml
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config {path} must be a top-level dict, got {type(cfg).__name__}")
    return cfg


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: str, max_rows: int | None = None) -> list[dict]:
    """Load JSONL, optionally limiting to *max_rows*."""
    rows: list[dict] = []
    with open(path) as f:
        for i, line in enumerate(f):
            if max_rows is not None and i >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def fabricate_dummy_samples(count: int = 200) -> list[dict]:
    """Generate schema-identical dummy samples for CPU-side validation.

    Uses the actual schema observed in finetune/gen/sft.jsonl.  No real data
    is required.  The system prompt, user message, and assistant response are
    all synthetic placeholders so packing + tokenization can be exercised
    without loading real examples.
    """
    import random
    intents = [
        "ask_step_1", "ask_step_2", "ask_step_3", "ask_prayer_meditation",
        "ask_resentment", "ask_forgiveness", "ask_sponsorship",
        "refusal_out_of_domain",
    ]
    difficulties = ["simple", "moderate", "complex"]
    registers = ["brief", "factual", "reflective"]
    sample_types = ["context", "refusal"]

    system_prompts = [
        "You are a knowledgeable, direct guide to recovery literature.",
        "You answer in two to four short sentences.",
        "You are a sponsor-style companion who helps the person think the question through.",
    ]

    samples: list[dict] = []
    for _ in range(count):
        intent = random.choice(intents)
        diff = random.choice(difficulties)
        reg = random.choice(registers)
        stype = random.choice(sample_types)

        if stype == "refusal":
            gold_blocks = []
            gold_docs = []
            distractor_blocks = []
            distractor_docs = []
        else:
            gold_blocks = [f"b{random.randint(0,99999):05d}", f"b{random.randint(0,99999):05d}"]
            gold_docs = ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions"]
            distractor_blocks = [f"b{random.randint(0,99999):05d}"]
            distractor_docs = ["narcotics-anonymous"]

        samples.append({
            "messages": [
                {"role": "system", "content": random.choice(system_prompts)},
                {"role": "user", "content": f"[DUMMY-{intent}-{diff}-{reg}] This is a dummy user question for dry-run validation."},
                {"role": "assistant", "content": f"[DUMMY-{intent}-{diff}-{reg}] This is a dummy assistant response for dry-run validation."},
            ],
            "meta": {
                "intent_id": intent,
                "difficulty": diff,
                "register": reg,
                "crisis_adjacent": False,
                "sample_type": stype,
                "gold_blocks": gold_blocks,
                "gold_docs": gold_docs,
                "distractor_blocks": distractor_blocks,
                "distractor_docs": distractor_docs,
            },
        })
    return samples


def split_dataset(
    rows: list[dict],
    train_frac: float = 0.98,
    stratify_key: str = "intent_id",
) -> tuple[list[dict], list[dict]]:
    """Stratified train/val split.

    Samples are grouped by *stratify_key* (extracted from ``.meta`` dict),
    then each group is split at *train_frac*.  This guarantees proportional
    representation of every intent in both splits.
    """
    import collections

    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        key = str(r.get("meta", {}).get(stratify_key, "unknown"))
        groups[key].append(r)

    train_all: list[dict] = []
    val_all: list[dict] = []
    for key, group in groups.items():
        group.sort(key=lambda x: json.dumps(x, sort_keys=True))  # deterministic
        n_train = max(1, int(len(group) * train_frac))
        train_all.extend(group[:n_train])
        val_all.extend(group[n_train:])

    # Shuffle deterministically
    import random
    rng = random.Random(42)
    rng.shuffle(train_all)
    rng.shuffle(val_all)
    return train_all, val_all


# ---------------------------------------------------------------------------
# Tokenizer + formatting
# ---------------------------------------------------------------------------

def load_tokenizer(model_name: str):
    """Load tokenizer (config-only — no model weights)."""
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )
    return tok


def format_messages(
    row: dict,
    tokenizer,
    seq_len: int,
) -> str:
    """Apply chat template to a single row's messages list."""
    messages = row["messages"]
    formatted: str = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return formatted


def tokenize_and_pack(
    texts: list[str],
    tokenizer,
    seq_len: int,
    packing: bool = True,
) -> dict[str, list]:
    """Tokenize and optionally pack sequences.

    When *packing* is True, multiple texts are concatenated (with EOS token
    between them) up to *seq_len* — this is the SFTTrainer packing behavior
    reproduced for CPU-side validation.

    Returns a dict with ``input_ids``, ``attention_mask``, ``labels`` lists
    (each a list of token-ID lists).
    """
    eos_id = tokenizer.eos_token_id
    if eos_id is None:
        raise ValueError("Tokenizer has no EOS token — cannot pack.")

    if not packing:
        # Simple truncation, no packing
        batch = tokenizer(
            texts,
            truncation=True,
            max_length=seq_len,
            padding=False,
            return_attention_mask=True,
        )
        # labels = input_ids for language modelling
        batch["labels"] = [ids[:] for ids in batch["input_ids"]]
        return batch

    # --- Packing ---
    input_ids_list: list[list[int]] = []
    attention_mask_list: list[list[int]] = []
    labels_list: list[list[int]] = []

    # Tokenize all texts individually
    all_ids: list[list[int]] = []
    for t in texts:
        ids = tokenizer.encode(t, add_special_tokens=False)
        if not ids:
            continue
        all_ids.append(ids + [eos_id])

    # Pack: concatenate until seq_len
    current_chunk: list[int] = []
    for ids in all_ids:
        if len(current_chunk) + len(ids) <= seq_len:
            current_chunk.extend(ids)
        else:
            # Flush current chunk (pad if needed)
            if current_chunk:
                chunk = current_chunk[:seq_len]
                pad_len = seq_len - len(chunk)
                input_ids_list.append(chunk + [tokenizer.pad_token_id or 0] * pad_len)
                attention_mask_list.append([1] * len(chunk) + [0] * pad_len)
                lbls = chunk[:]
                # Mask padding tokens in labels
                lbls_list = lbls + [-100] * pad_len
                labels_list.append(lbls_list)
            current_chunk = ids[:]

    # Don't forget the last chunk
    if current_chunk:
        chunk = current_chunk[:seq_len]
        pad_len = seq_len - len(chunk)
        input_ids_list.append(chunk + [tokenizer.pad_token_id or 0] * pad_len)
        attention_mask_list.append([1] * len(chunk) + [0] * pad_len)
        lbls = chunk[:]
        labels_list.append(lbls + [-100] * pad_len)

    return {
        "input_ids": input_ids_list,
        "attention_mask": attention_mask_list,
        "labels": labels_list,
    }


# ---------------------------------------------------------------------------
# Dry-run (CPU-side validation)
# ---------------------------------------------------------------------------

def dry_run(args: argparse.Namespace) -> int:
    """Validate everything possible without GPU or model weights.

    Returns 0 on success, 1 on failure.
    """
    import time
    t0 = time.time()
    errors: list[str] = []

    n_steps = args.dry_run
    n_samples = n_steps * 10  # 10 samples per step as a representative batch
    print(f"[dry-run] Validation mode: {n_steps} steps / {n_samples} samples")
    print(f"[dry-run] Config: {args.config}")
    print(f"[dry-run] Dataset: {args.dataset}")
    print(f"[dry-run] Output dir: {args.output_dir}")

    # ---- 1. Config parsing ----
    print("\n--- 1. Config parsing ---")
    try:
        cfg = load_config(args.config)
        print(f"  Model: {cfg['model']['name']}")
        print(f"  QLoRA r={cfg['qlora']['r']}, alpha={cfg['qlora']['lora_alpha']}")
        print(f"  Seq len: {cfg['training']['sequence_length']}")
        print(f"  Packing: {cfg['training']['packing']}")
        print(f"  LR schedule: {cfg['training']['lr_scheduler_type']}")
        print(f"  Warmup ratio: {cfg['training']['warmup_ratio']}")
        print(f"  Eval strategy: {cfg['evaluation']['eval_strategy']}, steps={cfg['evaluation']['eval_steps']}")
        print(f"  Output dir: {cfg.get('output_dir', args.output_dir)}")
        print(f"  OK — config parses cleanly")
    except Exception as e:
        errors.append(f"Config parsing failed: {e}")

    # ---- 2. Output directory ----
    print("\n--- 2. Output directory ---")
    out = Path(args.output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        # Check writable
        test_file = out / ".d3_dry_run_test"
        test_file.write_text("ok")
        test_file.unlink()
        print(f"  Output dir {out} exists and is writable")
    except Exception as e:
        errors.append(f"Output dir {out} not writable: {e}")

    # ---- 3. Checkpoint directory logic ----
    print("\n--- 3. Checkpoint directory logic ---")
    checkpoint_dir = out / "checkpoint"
    try:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        test_file = checkpoint_dir / ".d3_dry_run_test"
        test_file.write_text("ok")
        test_file.unlink()
        print(f"  Checkpoint dir {checkpoint_dir} works")
        # Resume-from logic: check if resume path exists
        if args.resume_from:
            rp = Path(args.resume_from)
            if rp.is_dir():
                print(f"  Resume-from path {rp} exists")
            else:
                errors.append(f"Resume-from path {rp} does not exist")
        # Save_total_limit logic: we keep 3 checkpoints
        print(f"  Save total limit: {cfg.get('checkpointing', {}).get('save_total_limit', 3)}")
    except Exception as e:
        errors.append(f"Checkpoint dir logic failed: {e}")

    # ---- 4. Tokenizer loads (config-only) ----
    print("\n--- 4. Tokenizer (config-only, no weights) ---")
    try:
        model_name = cfg["model"]["name"]
        tok = load_tokenizer(model_name)
        seq_len = args.seq_len or cfg["training"]["sequence_length"]
        print(f"  Model: {model_name}")
        print(f"  Tokenizer: {tok.__class__.__name__}")
        print(f"  Vocab size: {tok.vocab_size}")
        print(f"  EOS token: {tok.eos_token_id} ({tok.decode(tok.eos_token_id) if tok.eos_token_id is not None else 'N/A'})")
        print(f"  Pad token: {tok.pad_token_id}")
        print(f"  Chat template: {'present' if tok.chat_template else 'absent'}")
        # Apply chat template to dummy messages
        dummy_msg = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello?"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]
        formatted = tok.apply_chat_template(dummy_msg, tokenize=False, add_generation_prompt=False)
        print(f"  Chat template output ({len(formatted)} chars): {formatted[:80]}...")
        print(f"  OK — tokenizer loaded and chat template works")
    except Exception as e:
        errors.append(f"Tokenizer loading failed: {e}")

    # ---- 5. Dataset loading + schema validation ----
    print("\n--- 5. Dataset loading ---")
    try:
        ds_path = Path(args.dataset)
        if ds_path.is_file():
            rows = load_jsonl(args.dataset, max_rows=n_samples)
            print(f"  Loaded {len(rows)} rows from {args.dataset}")
        else:
            print(f"  Dataset {args.dataset} not found — fabricating {n_samples} dummy samples")
            rows = fabricate_dummy_samples(n_samples)

        # Schema check
        for i, r in enumerate(rows):
            if "messages" not in r:
                errors.append(f"Row {i}: missing 'messages' key")
                continue
            msgs = r["messages"]
            if not isinstance(msgs, list) or len(msgs) != 3:
                errors.append(f"Row {i}: expected 3 messages, got {len(msgs)}")
                continue
            roles = [m["role"] for m in msgs]
            if roles != ["system", "user", "assistant"]:
                errors.append(f"Row {i}: expected roles [system,user,assistant], got {roles}")
            for m in msgs:
                if "content" not in m:
                    errors.append(f"Row {i}: message missing 'content'")
            if "meta" in r:
                meta = r["meta"]
                for mk in ("intent_id", "difficulty", "register"):
                    if mk not in meta:
                        errors.append(f"Row {i}: meta missing '{mk}'")
        if errors:
            print(f"  Schema check FAILED")
        else:
            print(f"  Schema check OK — {len(rows)} rows valid")

        # Stats
        intents = set()
        difficulties = set()
        registers = set()
        for r in rows:
            meta = r.get("meta", {})
            if meta.get("intent_id"):
                intents.add(meta["intent_id"])
            if meta.get("difficulty"):
                difficulties.add(meta["difficulty"])
            if meta.get("register"):
                registers.add(meta["register"])
        print(f"  Intents: {len(intents)} ({', '.join(sorted(intents))})")
        print(f"  Difficulties: {', '.join(sorted(difficulties))}")
        print(f"  Registers: {', '.join(sorted(registers))}")
    except Exception as e:
        errors.append(f"Dataset loading failed: {e}")

    # ---- 6. Formatting + tokenization + packing ----
    print(f"\n--- 6. Tokenization + packing (seq_len={seq_len}) ---")
    try:
        formatted_texts = [
            format_messages(r, tok, seq_len) for r in rows
        ]
        total_chars = sum(len(t) for t in formatted_texts)
        print(f"  Formatted {len(formatted_texts)} samples ({total_chars} total chars)")

        # Tokenize with packing
        batched = tokenize_and_pack(formatted_texts, tok, seq_len, packing=True)
        n_packed = len(batched["input_ids"])
        print(f"  Packed into {n_packed} sequences (seq_len={seq_len})")
        print(f"  Input IDs shape: {n_packed} × {len(batched['input_ids'][0])}")
        print(f"  Labels shape: {n_packed} × {len(batched['labels'][0])}")
        avg_seq_len = sum(len(t) for t in batched["input_ids"]) / n_packed if n_packed else 0
        print(f"  Avg tokens per sequence: {avg_seq_len:.0f}")
        compression = len(formatted_texts) / n_packed if n_packed else 0
        print(f"  Packing compression ratio: {compression:.2f}x")

        # Verify all sequences are seq_len
        for i, ids in enumerate(batched["input_ids"]):
            if len(ids) != seq_len:
                errors.append(f"Sequence {i}: expected len {seq_len}, got {len(ids)}")
                break

        # Verify labels match input_ids (for non-padding positions)
        for i, (ids, lbls) in enumerate(zip(batched["input_ids"], batched["labels"])):
            for j, (id_, lbl) in enumerate(zip(ids, lbls)):
                if lbl != -100 and id_ != lbl:
                    errors.append(f"Sequence {i}, pos {j}: label {lbl} != input_id {id_}")
                    break
            if errors:
                break
        if not errors:
            print(f"  Label masking OK — all non-padding positions have label==input_id")
    except Exception as e:
        errors.append(f"Tokenization/packing failed: {e}")

    # ---- 7. Stratified split ----
    print(f"\n--- 7. Stratified train/val split ---")
    try:
        train_frac = cfg.get("dataset", {}).get("train_val_split", 0.98)
        stratify_key = cfg.get("dataset", {}).get("stratify_by", "intent_id")
        train_rows, val_rows = split_dataset(rows, train_frac, stratify_key)
        print(f"  Train: {len(train_rows)} rows, Val: {len(val_rows)} rows ({train_frac*100:.0f}/{100-train_frac*100:.0f} split)")

        # Verify stratification
        train_intents = {r["meta"]["intent_id"] for r in train_rows if "meta" in r}
        val_intents = {r["meta"]["intent_id"] for r in val_rows if "meta" in r}
        overlap = train_intents & val_intents
        only_val = val_intents - train_intents
        if only_val:
            print(f"  WARNING: {len(only_val)} intents ONLY in validation set: {only_val}")
        print(f"  Train intents: {len(train_intents)}, Val intents: {len(val_intents)}, Overlap: {len(overlap)}")
    except Exception as e:
        errors.append(f"Stratified split failed: {e}")

    # ---- 8. Argparse path validation (resume, overrides) ----
    print("\n--- 8. Argparse override validation ---")
    try:
        override_fields = []
        if args.learning_rate: override_fields.append(f"lr={args.learning_rate}")
        if args.num_epochs: override_fields.append(f"epochs={args.num_epochs}")
        if args.max_steps: override_fields.append(f"max_steps={args.max_steps}")
        if args.lr_scheduler_type: override_fields.append(f"scheduler={args.lr_scheduler_type}")
        if args.seq_len: override_fields.append(f"seq_len={args.seq_len}")
        if override_fields:
            print(f"  CLI overrides: {', '.join(override_fields)}")
        else:
            print(f"  No CLI overrides — using config defaults")
        print(f"  All argparse paths validable")
    except Exception as e:
        errors.append(f"Argparse validation failed: {e}")

    # ---- Summary ----
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    if errors:
        print(f"DRY-RUN FAILED — {len(errors)} error(s)")
        for e in errors:
            print(f"  • {e}")
        return 1
    else:
        print(f"DRY-RUN PASSED — {elapsed:.1f}s, all CPU-side checks OK")
        print(f"Ready for GPU training in a D1 window.")
        return 0


# ---------------------------------------------------------------------------
# Full training (requires GPU in D1 window)
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace, cfg: dict) -> int:
    """Run the full SFT training pipeline.

    NOTE: This function allocates GPU memory.  Only call inside a D1 window
          (after freeing at least one GPU from vLLM).
    """
    # unsloth must import before transformers/trl so its patches apply.
    # Vanilla peft 0.19 cannot wrap Gemma4ClippableLinear; unsloth's
    # get_peft_model knows the Gemma4 module layout. 4-bit/QLoRA dropped
    # 2026-07-08 — a 2B model on 96 GB cards gains nothing from
    # quantization; bf16 LoRA is simpler and faster.
    from unsloth import FastLanguageModel  # noqa: I001
    import torch
    from datasets import Dataset as HFDataset
    from trl import SFTConfig, SFTTrainer

    model_name = cfg["model"]["name"]
    qlora_cfg = cfg["qlora"]
    train_cfg = cfg["training"]
    eval_cfg = cfg["evaluation"]
    log_cfg = cfg["logging"]
    ckpt_cfg = cfg["checkpointing"]
    ds_cfg = cfg.get("dataset", {})
    output_dir = args.output_dir
    seq_len = args.seq_len or train_cfg["sequence_length"]
    seed = cfg.get("seed", 42)

    # ---- Load model + tokenizer via unsloth (bf16, no quantization) ----
    print(f"Loading model via unsloth (bf16, LoRA): {model_name}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name,
        max_seq_length=seq_len,
        dtype=torch.bfloat16,
        load_in_4bit=False,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    model = FastLanguageModel.get_peft_model(
        model,
        r=qlora_cfg["r"],
        lora_alpha=qlora_cfg["lora_alpha"],
        target_modules=qlora_cfg.get("target_modules"),
        lora_dropout=qlora_cfg.get("lora_dropout", 0.05),
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=seed,
    )

    # ---- Load dataset ----
    print(f"Loading dataset: {args.dataset}")
    rows = load_jsonl(args.dataset)
    train_frac = ds_cfg.get("train_val_split", 0.98)
    stratify_key = ds_cfg.get("stratify_by", "intent_id")
    train_rows, val_rows = split_dataset(rows, train_frac, stratify_key)
    print(f"  Train: {len(train_rows)}, Val: {len(val_rows)}")

    def format_fn(row: dict) -> dict[str, str]:
        return {"text": format_messages(row, tokenizer, seq_len)}

    train_texts = [format_fn(r)["text"] for r in train_rows]
    val_texts = [format_fn(r)["text"] for r in val_rows]
    train_ds = HFDataset.from_dict({"text": train_texts})
    val_ds = HFDataset.from_dict({"text": val_texts})

    # ---- SFT config ----
    max_steps = args.max_steps if args.max_steps is not None else train_cfg.get("max_steps", -1)
    num_epochs = args.num_epochs if args.num_epochs is not None else train_cfg.get("num_train_epochs", 3)
    lr = args.learning_rate if args.learning_rate is not None else train_cfg.get("learning_rate", 2e-4)
    lr_scheduler = args.lr_scheduler_type or train_cfg.get("lr_scheduler_type", "cosine")

    sft_config = SFTConfig(
        output_dir=output_dir,
        # Training
        per_device_train_batch_size=args.per_device_train_batch_size or train_cfg.get("per_device_train_batch_size", 4),
        gradient_accumulation_steps=args.gradient_accumulation_steps or train_cfg.get("gradient_accumulation_steps", 2),
        num_train_epochs=num_epochs,
        max_steps=max_steps,
        learning_rate=lr,
        lr_scheduler_type=lr_scheduler,
        warmup_ratio=train_cfg.get("warmup_ratio", 0.1),
        weight_decay=train_cfg.get("weight_decay", 0.01),
        optim=train_cfg.get("optim", "adamw_torch_fused"),
        gradient_checkpointing=train_cfg.get("gradient_checkpointing", True),
        bf16=train_cfg.get("bf16", True),
        tf32=train_cfg.get("tf32", True),
        max_grad_norm=train_cfg.get("max_grad_norm", 1.0),
        # Sequence
        max_length=seq_len,
        packing=train_cfg.get("packing", True),
        # Evaluation
        eval_strategy=eval_cfg.get("eval_strategy", "steps"),
        eval_steps=eval_cfg.get("eval_steps", 50),
        eval_on_start=eval_cfg.get("eval_on_start", True),
        per_device_eval_batch_size=eval_cfg.get("per_device_eval_batch_size", 4),
        # Logging
        logging_strategy=log_cfg.get("logging_strategy", "steps"),
        logging_steps=log_cfg.get("logging_steps", 10),
        report_to=log_cfg.get("report_to", "none"),
        # Checkpointing
        save_strategy=ckpt_cfg.get("save_strategy", "steps"),
        save_steps=ckpt_cfg.get("save_steps", 100),
        save_total_limit=ckpt_cfg.get("save_total_limit", 3),
        load_best_model_at_end=ckpt_cfg.get("load_best_model_at_end", False),
        # Misc
        seed=seed,
        remove_unused_columns=True,
        dataset_text_field="text",
        dataloader_num_workers=2,
        dataloader_pin_memory=True,
    )

    # ---- Trainer ----
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tokenizer,
    )

    # ---- Checkpoint resume ----
    if args.resume_from:
        print(f"Resuming from checkpoint: {args.resume_from}")
        trainer.train(resume_from_checkpoint=args.resume_from)
    else:
        trainer.train()

    # ---- Save final ----
    print(f"Saving final model to {output_dir}")
    trainer.save_model(output_dir)

    # ---- Log final metrics ----
    metrics_path = Path(output_dir) / "metrics.json"
    log_history = trainer.state.log_history
    with open(metrics_path, "w") as f:
        json.dump(log_history, f, indent=2, default=str)
    print(f"Metrics saved to {metrics_path}")

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve paths
    args.config = str(Path(args.config).resolve())
    args.dataset = str(Path(args.dataset).resolve())
    args.output_dir = str(Path(args.output_dir).resolve())

    # ---- Dry-run: CPU-side only ----
    if args.dry_run and args.dry_run > 0:
        return dry_run(args)

    # ---- Full training ----
    cfg = load_config(args.config)
    return train(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
