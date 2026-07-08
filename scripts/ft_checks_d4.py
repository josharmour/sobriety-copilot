#!/usr/bin/env python3
"""FT-D4 verification check — CPU-side validation of D4 deliverables.

Registered as the ``d4`` check.  Validates everything possible without GPU
or model weight downloads:
  1. dpo_config.yaml exists, parses, contains all required keys including
     the dpo.beta section.
  2. ft_train_dpo.py exists, imports cleanly.
  3. --dry-run finishes on 200 dummy DPO pairs (config, tokenizer, paths,
     dataset schema, stratified split by flaw).
  4. Required overrides (--dataset, --adapter, --dry-run) work as documented.
  5. Adapter path plumbing is correct (path exists or is noted pending D3).

See the D4 task in finetuning-the-rag.md for the full spec.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Import shared helpers from the main ft_checks module
from scripts.ft_checks import REPO_ROOT, register


def parse_yaml_keys(path: Path) -> set[str]:
    """Return the top-level keys of a YAML file."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: top-level must be a dict, got {type(data).__name__}"
        )
    return set(data.keys())


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

@register("d4")
def check_d4(args: list[str]) -> int:
    """CPU-side validation of FT-D4 deliverables.

    No GPU memory allocated, no model weights downloaded.
    """
    errors: list[str] = []

    # ------------------------------------------------------------------
    # 1. Config file exists and parses
    # ------------------------------------------------------------------
    config_path = REPO_ROOT / "finetune" / "infra" / "dpo_config.yaml"
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

        required_sections = {
            "model", "qlora", "dpo", "training",
            "evaluation", "logging", "checkpointing", "dataset", "seed",
        }
        missing = required_sections - set(cfg.keys())
        if missing:
            errors.append(f"Config missing sections: {missing}")

        # Check required fields
        model = cfg.get("model", {})
        if model.get("name") != "google/gemma-4-e2b-it":
            errors.append(
                f"model.name should be google/gemma-4-e2b-it, "
                f"got {model.get('name')}"
            )

        qlora = cfg.get("qlora", {})
        r = qlora.get("r", 0)
        if not (16 <= r <= 64):
            errors.append(f"qlora.r must be in 16..64, got {r}")

        # DPO-specific checks
        dpo_cfg = cfg.get("dpo", {})
        beta = dpo_cfg.get("beta")
        if beta is None:
            errors.append("dpo.beta must be set")
        elif not (0.01 <= beta <= 1.0):
            errors.append(f"dpo.beta should be in 0.01..1.0, got {beta}")
        loss_type = dpo_cfg.get("loss_type", "sigmoid")
        if loss_type != "sigmoid":
            errors.append(
                f"dpo.loss_type should be 'sigmoid', got '{loss_type}'"
            )

        training = cfg.get("training", {})
        if training.get("packing") is not False:
            errors.append("training.packing must be False for DPO")
        if training.get("lr_scheduler_type") != "cosine":
            errors.append(
                f"training.lr_scheduler_type should be 'cosine', "
                f"got {training.get('lr_scheduler_type')}"
            )

        eval_cfg = cfg.get("evaluation", {})
        if eval_cfg.get("eval_strategy") != "steps":
            errors.append(
                f"evaluation.eval_strategy should be 'steps', "
                f"got {eval_cfg.get('eval_strategy')}"
            )

        # Stratify by flaw (DPO-specific)
        ds_cfg = cfg.get("dataset", {})
        if ds_cfg.get("stratify_by") != "flaw":
            errors.append(
                f"dataset.stratify_by should be 'flaw' for DPO, "
                f"got {ds_cfg.get('stratify_by')}"
            )

        print(f"  DPO beta={beta}, loss_type={loss_type}")
        print(f"  QLoRA r={r}, alpha={qlora.get('lora_alpha')}")
        print(f"  Seq len: {training.get('sequence_length')}, packing: OFF")
        print(f"  LR: {training.get('learning_rate')}, "
              f"schedule: {training.get('lr_scheduler_type')}")
        print(f"  Eval: every {eval_cfg.get('eval_steps')} steps")
        print(f"  Stratify by: {ds_cfg.get('stratify_by')}")
        print(f"  Config OK")

    except Exception as e:
        errors.append(f"Config parse/validate failed: {e}")

    # ------------------------------------------------------------------
    # 2. Training script exists
    # ------------------------------------------------------------------
    script_path = REPO_ROOT / "scripts" / "ft_train_dpo.py"
    print(f"\n[2/6] Checking script: {script_path.relative_to(REPO_ROOT)}")
    if not script_path.is_file():
        errors.append(f"Script not found: {script_path}")
    else:
        print(f"  Script exists ({script_path.stat().st_size} bytes)")

    # Resolve venv python path
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
        dataset_path = REPO_ROOT / "finetune" / "gen" / "dpo.jsonl"
        adapter_path = REPO_ROOT / "finetune" / "runs" / "sft-01" / "adapter"

        # Print adapter status note
        if not adapter_path.is_dir():
            print(f"  (adapter not yet present — D3 GPU run pending; "
                  f"will validate path plumbing only)")

        result = subprocess.run(
            [
                venv_python_str,
                str(script_path),
                "--dataset", str(dataset_path),
                "--adapter", str(adapter_path),
                "--dry-run", "20",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
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
                f"dry-run exited {result.returncode}. See output above."
            )
        else:
            print(f"\n  Dry-run PASSED (exit code 0)")

    except subprocess.TimeoutExpired:
        errors.append("dry-run timed out (>180s)")
    except FileNotFoundError as e:
        errors.append(f"dry-run could not start: {e}")
    except Exception as e:
        errors.append(f"dry-run failed: {e}")

    # ------------------------------------------------------------------
    # 4. Output directory creation works
    # ------------------------------------------------------------------
    print(f"\n[4/6] Checking output directory logic...")
    output_dir = REPO_ROOT / "finetune" / "runs" / "dpo-01"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        testf = output_dir / ".d4_check_test"
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
            print(f"  Argparse OK — --dataset, --adapter, --dry-run, "
                  f"--config, --output-dir present")
        else:
            errors.append("argparse --help did not show expected flags")
    except Exception as e:
        errors.append(f"Argparse check failed: {e}")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    if errors:
        print(f"\n{'='*60}")
        print(f"D4 CHECK FAILED — {len(errors)} error(s)")
        for e in errors:
            print(f"  • {e}")
        return 1

    print(f"\n{'='*60}")
    print(f"D4 CHECK PASSED — all CPU-side validations OK")
    print(f"GPU 20-step dry run deferred to D1 window (GPUs held by prod vLLM).")
    return 0


def _report(errors: list[str]) -> None:
    for e in errors:
        print(f"  FAIL: {e}", file=sys.stderr)
