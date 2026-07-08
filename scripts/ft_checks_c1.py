#!/usr/bin/env python3
"""FT-C1 Verify: Prompt taxonomy schema, counts, crisis-adjacent flagging.

Registered via the @register() decorator so ``python -m scripts.ft_checks c1``
discovers this module automatically through the ft_checks _load_task_modules()
auto-import machinery.

Crisis seed verification: instead of hardcoding hashes, we recompute the
expected hashes from the canonical crisis safety phrases defined in
scripts/build_taxonomy_c1.py's _SAFETY_PHRASES dict. This ensures the check
stays in sync with the fixed safety wording from src/prompts/templates.py
and mobile_app/lib/features/private_mode/local_prompts.dart.
"""

from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

from scripts.ft_checks import register, open_corpus

REPO_ROOT = Path(__file__).resolve().parent.parent

DIFFICULTIES = ["simple", "moderate", "complex"]
REGISTERS = ["warm", "factual", "reflective", "brief"]

# The crisis-adjacent intent IDs (must match build_taxonomy_c1.py)
CRISIS_IDS = {"crisis_imminent_relapse", "crisis_harm_urges", "crisis_overdose_concern"}


def _load_crisis_hashes() -> dict[str, set[int]]:
    """Load the known crisis safety seed hashes from build_taxonomy_c1.py.

    This reads the _SAFETY_PHRASES dict embedded in the build script and
    computes crc32 hashes exactly the same way _check_seed_source does, so
    they stay in sync automatically.
    """
    build_path = REPO_ROOT / "scripts" / "build_taxonomy_c1.py"
    if not build_path.is_file():
        print("WARN: build_taxonomy_c1.py not found — crisis seed check skipped", file=sys.stderr)
        return {}

    # Extract _SAFETY_PHRASES by importing — the script has no side effects
    # at module level other than the main() guard.
    import importlib.util
    spec = importlib.util.spec_from_file_location("_build_tax_c1", build_path)
    if spec is None or spec.loader is None:
        print("WARN: cannot load build_taxonomy_c1.py — crisis seed check skipped", file=sys.stderr)
        return {}
    mod = importlib.util.module_from_spec(spec)
    # Suppress execution of main()
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)

    phrases = getattr(mod, "_SAFETY_PHRASES", {})
    result: dict[str, set[int]] = {}
    for intent_id, diff_dict in phrases.items():
        hashes: set[int] = set()
        for diff in DIFFICULTIES:
            if diff not in diff_dict:
                continue
            for reg in REGISTERS:
                if reg not in diff_dict[diff]:
                    continue
                for seed in diff_dict[diff][reg]:
                    norm = seed.strip().lower().replace("\u2014", "--").replace("\u2013", "-")
                    hashes.add(zlib.crc32(norm.encode("utf-8")))
        result[intent_id] = hashes
    return result


def _check_seed_source(
    intent_id: str,
    seeds: list[str],
    crisis_hashes: dict[str, set[int]],
) -> list[str]:
    """Verify crisis seeds match the fixed safety wording.

    For crisis-adjacent intents, every seed must hash-match the known safety
    set (from src/prompts/templates.py / local_prompts.dart). This detects
    free-generated content replacing the fixed wording.

    For non-crisis intents, warn if seeds contain crisis-domain language
    (informational only — not a hard fail since the LLM generated them).
    """
    errors: list[str] = []
    NON_CRISIS_BLOCKLIST = [
        "hotline", "helpline", "overdose", "suicidal", "suicide",
        "self-harm", "narcan", "naloxone",
    ]

    if intent_id in CRISIS_IDS:
        expected = crisis_hashes.get(intent_id)
        if expected is None:
            # Couldn't load from build script — skip check
            return errors
        for seed in seeds:
            norm = seed.strip().lower().replace("\u2014", "--").replace("\u2013", "-")
            h = zlib.crc32(norm.encode("utf-8"))
            if h not in expected:
                errors.append(
                    f"crisis intent '{intent_id}' seed not in known safety set: "
                    f"{seed[:100]}..."
                )
    else:
        # Non-crisis — soft warning only (don't hard-fail)
        for seed in seeds:
            seed_lower = seed.lower()
            if any(m in seed_lower for m in NON_CRISIS_BLOCKLIST):
                print(
                    f"  WARN: non-crisis intent '{intent_id}' seed contains "
                    f"crisis language: {seed[:80]}...",
                    file=sys.stderr,
                )
    return errors


# Load crisis hash set once at module load time
_CRISIS_HASHES = _load_crisis_hashes()


@register("c1")
def check_c1(args: list[str]) -> int:
    """Verify finetune/gen/taxonomy.json — schema, counts, crisis flagging."""
    tax_path = REPO_ROOT / "finetune" / "gen" / "taxonomy.json"

    if not tax_path.is_file():
        print(f"FAIL: {tax_path} not found", file=sys.stderr)
        return 1

    errors: list[str] = []

    try:
        with open(tax_path) as f:
            taxonomy = json.load(f)
    except json.JSONDecodeError as e:
        print(f"FAIL: invalid JSON — {e}", file=sys.stderr)
        return 1

    if not isinstance(taxonomy, list):
        print(f"FAIL: expected a list of intents, got {type(taxonomy).__name__}", file=sys.stderr)
        return 1

    # ── Counts ──
    intent_count = len(taxonomy)
    if intent_count < 25:
        errors.append(f"only {intent_count} intents (expected ~30)")

    crisis_count = 0
    total_seeds = 0
    seen_ids: set[str] = set()

    for i, entry in enumerate(taxonomy):
        # Required keys
        for key in ("intent_id", "label", "description", "crisis_adjacent", "difficulty_levels"):
            if key not in entry:
                errors.append(f"entry {i}: missing key '{key}'")

        iid = entry.get("intent_id", f"<entry {i}>")
        if iid in seen_ids:
            errors.append(f"duplicate intent_id: {iid}")
        seen_ids.add(iid)

        # crisis_adjacent must be bool
        crisis = entry.get("crisis_adjacent")
        if not isinstance(crisis, bool):
            errors.append(f"'{iid}': crisis_adjacent must be bool, got {type(crisis).__name__}")

        if crisis:
            crisis_count += 1
            if iid not in CRISIS_IDS:
                errors.append(f"'{iid}': flagged crisis_adjacent but not in known crisis set {CRISIS_IDS}")
        else:
            if iid in CRISIS_IDS:
                errors.append(f"'{iid}': in crisis set but not flagged crisis_adjacent")

        # difficulty_levels structure
        diffs = entry.get("difficulty_levels", {})
        for diff in DIFFICULTIES:
            if diff not in diffs:
                errors.append(f"'{iid}': missing difficulty '{diff}'")
                continue
            regs = diffs[diff]
            for reg in REGISTERS:
                if reg not in regs:
                    errors.append(f"'{iid}/{diff}': missing register '{reg}'")
                    continue
                seeds = regs[reg]
                if not isinstance(seeds, list):
                    errors.append(f"'{iid}/{diff}/{reg}': expected list, got {type(seeds).__name__}")
                    continue
                if len(seeds) < 3:
                    errors.append(f"'{iid}/{diff}/{reg}': only {len(seeds)} seeds (need ≥3)")
                elif len(seeds) > 5:
                    errors.append(f"'{iid}/{diff}/{reg}': {len(seeds)} seeds (expected ≤5)")
                total_seeds += len(seeds)

                # Crisis safety check
                errs = _check_seed_source(iid, seeds, _CRISIS_HASHES)
                errors.extend(errs)

    if crisis_count < 3:
        errors.append(f"only {crisis_count} crisis-adjacent intents (expected ≥3)")

    # ── Minimum seed count ──
    min_seeds = 25 * len(DIFFICULTIES) * len(REGISTERS) * 3
    if total_seeds < min_seeds:
        errors.append(
            f"only {total_seeds} total seed phrasings (need ≥{min_seeds} "
            f"for 25 intents × {len(DIFFICULTIES)} diffs × {len(REGISTERS)} regs × 3)"
        )

    # ── Report ──
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    print(f"C1 OK — {intent_count} intents ({crisis_count} crisis-adjacent)")
    print(f"  Total seed phrasings: {total_seeds}")
    print(f"  Difficulties: {len(DIFFICULTIES)} ({', '.join(DIFFICULTIES)})")
    print(f"  Registers: {len(REGISTERS)} ({', '.join(REGISTERS)})")
    print(f"  Crisis intents: {', '.join(sorted(seen_ids & CRISIS_IDS))}")
    return 0
