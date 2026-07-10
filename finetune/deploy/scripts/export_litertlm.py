#!/usr/bin/env python3
"""
FT-F2: Export wrapper — apply patch + run Route B (merged model → .litertlm).

Usage
-----
    export_litertlm.py              # apply patch + run full export
    export_litertlm.py --dry-run    # apply patch + print command only (no export)

Requires litert-torch 0.9.1 + Python 3.11.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
PATCH_PATH = HERE / "patch_litert_gemma4.py"
SFT_MERGED_DIR = Path("/home/joshu/ft-runs/sft-merged")
OUTPUT_DIR = Path("/home/joshu/ft-runs/litertlm-export")

# ── Export command (the exact Route B invocation from f2_report.md) ───────
EXPORT_CMD = [
    sys.executable or "python3",
    "-m",
    "litert_torch.generative.export_hf",
    "export",
    str(SFT_MERGED_DIR),
    str(OUTPUT_DIR),
    "--task", "image_text_to_text",
    "--prefill_lengths", "128,256",
    "--cache_length", "2048",
    "--externalize_embedder", "True",
    "--bundle_litert_lm", "True",
    "--use_jinja_template", "True",
    "--quantization_recipe", "None",
    "--keep_temporary_files", "True",
]


def run_patch() -> bool:
    """Apply the Gemma4 cache-layer patch.  Returns success."""
    result = subprocess.run(
        [sys.executable, str(PATCH_PATH)],
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(f"[export] ERROR: patch failed (exit {result.returncode})")
        return False
    return True


def check_prerequisites() -> bool:
    """Verify paths and dependencies exist."""
    errors = []

    if not SFT_MERGED_DIR.exists():
        errors.append(f"merged model not found: {SFT_MERGED_DIR}")

    if not PATCH_PATH.exists():
        errors.append(f"patch script not found: {PATCH_PATH}")

    try:
        import litert_torch  # noqa: F401
    except ImportError:
        errors.append(
            "litert-torch is not installed in this environment.\n"
            "  Create a Python 3.11 venv:     python3.11 -m venv .venv-f2\n"
            "  Activate:                        source .venv-f2/bin/activate\n"
            "  Install:                         pip install litert-torch==0.9.1"
        )

    if errors:
        print("[export] Prerequisites check FAILED:")
        for e in errors:
            print(f"  • {e}")
        return False

    return True


def run_export(dry_run: bool = False) -> bool:
    """Run the Route B export.  Returns success."""
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[export] Input:  {SFT_MERGED_DIR}")
    print(f"[export] Output: {OUTPUT_DIR}")
    print(f"[export] Python: {sys.version}")
    print()

    if dry_run:
        print("[export] DRY RUN — would execute:")
        print(f"    {' '.join(EXPORT_CMD)}")
        return True

    print("[export] Starting export (this will take hours) ...")
    print(f"[export] Command: {' '.join(EXPORT_CMD)}")
    print()

    env = os.environ.copy()

    # ── optional: prevent nvidia CUDA libs from stealing device handles ─────
    # If you are on a machine with NVIDIA GPUs but want to run on CPU,
    # uncomment the next lines:
    # env["CUDA_VISIBLE_DEVICES"] = "-1"
    # env["ROCR_VISIBLE_DEVICES"] = "-1"

    with subprocess.Popen(
        EXPORT_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        env=env,
    ) as proc:
        for line in proc.stdout:
            print(f"  {line}", end="")
            sys.stdout.flush()
        proc.wait()
        returncode = proc.returncode

    print()
    if returncode == 0:
        print(f"[export] ✓ Completed successfully.")
        # List output files
        for f in sorted(OUTPUT_DIR.iterdir()):
            if f.is_file():
                sz = f.stat().st_size / 1e6
                print(f"         {f.name} ({sz:.1f} MB)")
            else:
                sz = sum(p.stat().st_size for p in f.rglob("*")) / 1e6
                print(f"         {f.name}/ ({sz:.1f} MB)")
        return True
    else:
        print(f"[export] ✗ FAILED (exit {returncode})")
        return False


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="FT-F2: patch + export merged SFT model to .litertlm"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apply patch and print command but do NOT run export",
    )
    parser.add_argument(
        "--skip-patch",
        action="store_true",
        help="Skip the monkey-patch step (only run export)",
    )
    args = parser.parse_args()

    print("═" * 60)
    print("  FT-F2: Route B — Merged HF Model → .litertlm")
    print("═" * 60)
    print()

    # 1. Check prerequisites
    if not check_prerequisites():
        return 1

    # 2. Apply monkey-patch
    if not args.skip_patch:
        print("── Step 1: Monkey-patch litert-torch Gemma4 cache layer ──")
        if not run_patch():
            return 1
        print()
    else:
        print("── Step 1: Skipped (--skip-patch) ──\n")

    # 3. Run export
    print("── Step 2: Model export ──")
    success = run_export(dry_run=args.dry_run)
    print()

    if success or args.dry_run:
        print("[export] Route B success path ready.")
        return 0
    else:
        print("[export] Route B failed — see diagnostics above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
