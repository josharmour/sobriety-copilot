#!/usr/bin/env python3
"""FT-D2 Verify: Training environment — delegates to setup_env.sh --check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO_ROOT = Path(__file__).resolve().parent.parent


@register("d2")
def check_d2(args: list[str]) -> int:
    """Verify the training environment venv exists and passes smoke test.

    Delegates to:
        bash finetune/infra/setup_env.sh --check
    """
    script = REPO_ROOT / "finetune" / "infra" / "setup_env.sh"

    if not script.is_file():
        print(f"FAIL: {script} not found", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["bash", str(script), "--check"],
        capture_output=False,
        text=True,
    )

    if result.returncode != 0:
        print(f"FAIL: setup_env.sh --check exited {result.returncode}", file=sys.stderr)
        return 1

    print("FT-D2 training environment OK")
    return 0
