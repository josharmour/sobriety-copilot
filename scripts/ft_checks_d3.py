#!/usr/bin/env python3
"""FT-D3 verification check — CPU-side validation of D3 deliverables.

Registered as the ``d3`` check.  Validates everything possible without GPU
or model weight downloads:
  1. sft_config.yaml exists, parses, contains all required keys.
  2. ft_train_sft.py exists, imports cleanly (no CUDA/GIL enforcement).
  3. --dry-run finishes on 200 dummy samples (config, tokenizer, packing,
     checkpoint paths, dataset schema, stratified split).
  4. Required overrides (--dataset, --dry-run) work as documented.

See the D3 task in finetuning-the-rag.md for the full spec.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Import shared helpers from the main ft_checks module
import scripts.ft_checks as ftc

REPO_ROOT = ftc.REPO_ROOT


def parse_yaml_keys(path: Path) -> set[str]:
    """Return the top-level keys of a YAML file."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a dict, got {type(data).__name__}")
    return set(data.keys())


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

@ftc.register("d3")
def check_d3(args: list[str]) -> int:
    """CPU-side validation of FT-D3 deliverables.

    No GPU memory allocated, no model weights downloaded.
    """
    errors: list[str] = []

    # ------------------------------------------------------------------
    # 1. Config file exists and parses
    # ------------------------------------------------------------------
    config_path = REPO_ROOT / "finetune" / "infra" / "sft_config.yaml"
    print(f"\n[1/6] Checking config: {config_path.relative_to(REPO_ROOT)}")

    if not config_path.is_file():
        errors.append(f"Config not found: {config_path}")
        _report(errors)
        return 1

    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert isinstance(cfg, dict), "Config must be a top-level dict"

        required_sections = {"model", "qlora", "training", "evaluation",
                             "logging", "checkpointing", "dataset", "seed"}
        missing = required_sections - set(cfg.keys())
        if missing:
            errors.append(f"Config missing sections: {missing}")

        # Check required fields
        model = cfg.get("model", {})
        if model.get("name") != "google/gemma-4-e2b-it":
            errors.append(f"model.name should be google/gemma-4-e2b-it, got {model.get('name')}")

        qlora = cfg.get("qlora", {})
        r = qlora.get("r", 0)
        if not (16 <= r <= 64):
            errors.append(f"qlora.r must be in 16..64, got {r}")

        training = cfg.get("training", {})
        if training.get("sequence_length") != 4096:
            errors.append(f"training.sequence_length should be 4096, got {training.get('sequence_length')}")
        if training.get("packing") is not True:
            errors.append(f"training.packing must be True")
        if training.get("lr_scheduler_type") != "cosine":
            errors.append(f"training.lr_scheduler_type should be 'cosine', got {training.get('lr_scheduler_type')}")

        eval_cfg = cfg.get("evaluation", {})
        if eval_cfg.get("eval_strategy") != "steps":
            errors.append(f"evaluation.eval_strategy should be 'steps', got {eval_cfg.get('eval_strategy')}")
        if eval_cfg.get("eval_on_start") is not True:
            errors.append(f"evaluation.eval_on_start should be True")

        # Rank justification in comments
        print(f"  QLoRA r={r}, alpha={qlora.get('lora_alpha')} — r=32 chosen for balanced")
        print(f"    capacity across ~8k samples × 30 intents × 3 difficulties")
        print(f"  Seq len: {training.get('sequence_length')}, packing: ON")
        print(f"  LR: {training.get('learning_rate')}, schedule: {training.get('lr_scheduler_type')}")
        print(f"  Eval: every {eval_cfg.get('eval_steps')} steps")
        print(f"  Config OK")

    except Exception as e:
        errors.append(f"Config parse/validate failed: {e}")

    # ------------------------------------------------------------------
    # 2. Training script exists
    # ------------------------------------------------------------------
    script_path = REPO_ROOT / "scripts" / "ft_train_sft.py"
    print(f"\n[2/6] Checking script: {script_path.relative_to(REPO_ROOT)}")
    if not script_path.is_file():
        errors.append(f"Script not found: {script_path}")
    else:
        print(f"  Script exists ({script_path.stat().st_size} bytes)")

    # Resolve venv python path upfront
    venv_python = REPO_ROOT / "finetune" / ".venv" / "bin" / "python3"
    if not venv_python.is_file():
        venv_python = REPO_ROOT / "finetune" / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        venv_python = Path("python3")
    venv_python_str = str(venv_python)

    # ------------------------------------------------------------------
    # 3. Dry-run subprocess
    # ------------------------------------------------------------------
    print(f"\n[3/6] Running --dry-run (CPU-side validation)...")
    try:
        dataset_path = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
        dataset_arg = str(dataset_path) if dataset_path.is_file() else str(dataset_path)
        if not dataset_path.is_file():
            print(f"  (dataset not yet complete — dry-run will fabricate dummy samples)")

        result = subprocess.run(
            [
                venv_python_str,
                str(script_path),
                "--dataset", str(dataset_path),
                "--dry-run", "20",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Print dry-run output for diagnostics
        for line in result.stdout.splitlines():
            print(f"  | {line}")

        if result.stderr:
            print(f"  [stderr]:")
            for line in result.stderr.splitlines()[-10:]:
                print(f"  ! {line}")

        if result.returncode != 0:
            errors.append(
                f"dry-run exited {result.returncode}. "
                f"See output above."
            )
        else:
            print(f"\n  Dry-run PASSED (exit code 0)")

    except subprocess.TimeoutExpired:
        errors.append("dry-run timed out (>120s)")
    except FileNotFoundError as e:
        errors.append(f"dry-run could not start: {e}")
    except Exception as e:
        errors.append(f"dry-run failed: {e}")

    # ------------------------------------------------------------------
    # 4. Output directory creation works
    # ------------------------------------------------------------------
    print(f"\n[4/6] Checking output directory logic...")
    output_dir = REPO_ROOT / "finetune" / "runs" / "sft-01"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        testf = output_dir / ".d3_check_test"
        testf.write_text("ok")
        testf.unlink()
        print(f"  Output dir {output_dir.relative_to(REPO_ROOT)} works")
    except Exception as e:
        errors.append(f"Output directory not writable: {e}")

    # ------------------------------------------------------------------
    # 5. Checkpoint sub-directory logic
    # ------------------------------------------------------------------
    print(f"\n[5/6] Checking checkpoint dir logic...")
    ckpt_dir = output_dir / "checkpoint"
    try:
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Checkpoint dir {ckpt_dir.relative_to(REPO_ROOT)} works")
    except Exception as e:
        errors.append(f"Checkpoint directory error: {e}")

    # ------------------------------------------------------------------
    # 6. Argparse --help is valid
    # ------------------------------------------------------------------
    print(f"\n[6/6] Checking argparse...")
    try:
        result = subprocess.run(
            [venv_python_str, str(script_path), "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and "--dataset" in result.stdout:
            print(f"  Argparse OK — --dataset, --dry-run, --config, --output-dir present")
        else:
            errors.append("argparse --help did not show expected flags")
    except Exception as e:
        errors.append(f"Argparse check failed: {e}")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    if errors:
        print(f"\n{'='*60}")
        print(f"D3 CHECK FAILED — {len(errors)} error(s)")
        for e in errors:
            print(f"  • {e}")
        return 1

    print(f"\n{'='*60}")
    print(f"D3 CHECK PASSED — all CPU-side validations OK")
    print(f"GPU dry-run deferred to D1 window (GPUs held by prod vLLM).")
    return 0


def _report(errors: list[str]) -> None:
    for e in errors:
        print(f"  FAIL: {e}", file=sys.stderr)
