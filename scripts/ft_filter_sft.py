#!/usr/bin/env python3
"""
FT-C3: Quality filter for SFT dataset using dsv4 judge.

Checks every sample in finetune/gen/sft.jsonl against a 5-axis rubric:
  grounded, voice, hotline_discipline, register_fit, refusal_correctness

Drops any sample with a hard-fail on any axis.
Writes finetune/gen/sft.filtered.jsonl + finetune/gen/filter_report.json.

Checkpointed and resumable: re-run to continue from the last checkpoint.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
OUTPUT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "filter_report.json"
CHECKPOINT_PATH = REPO_ROOT / "finetune" / "gen" / ".filter_checkpoint.json"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LLM_BASE_URL = "http://10.0.0.10:8002/v1"
LLM_MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
MAX_CONCURRENCY = 16
BATCH_SIZE = 200  # checkpoint every N samples
RETRY_LIMIT = 3

# ---------------------------------------------------------------------------
# Judge system prompt
# ---------------------------------------------------------------------------
JUDGE_SYSTEM_PROMPT = """You are a quality judge for a recovery assistant's training data. Evaluate the sample strictly per the rubric below.

Respond with ONLY valid JSON in this exact structure (no markdown, no code fences):
{"grounded": "PASS"|"FAIL"|"SKIP", "grounded_note": "...",
 "voice": "PASS"|"FAIL", "voice_note": "...",
 "hotline_discipline": "PASS"|"FAIL", "hotline_note": "...",
 "register_fit": "PASS"|"FAIL", "register_note": "...",
 "refusal_correctness": "PASS"|"FAIL", "refusal_note": "...",
 "overall": "KEEP"|"DROP",
 "drop_reason": "which axis failed — empty if KEEP"}

RUBRIC (PASS = sample is fine on this axis; FAIL = hard violation — drop immediately):

1. GROUNDED (only for context samples with gold blocks — SKIP otherwise):
   Does the answer's substance come from the provided gold passage(s)?
   FAIL if the answer contradicts any gold passage or invents specific content/claims not present in them.

2. VOICE:
   FAIL if any of these appear in the assistant answer:
   - Fake lived experience ("when I got sober", "my sponsor taught me", "as someone in recovery", "I remember when", etc.)
   - Bracketed citation markers like [1] or [2]
   - Filenames or file extensions (.pdf, .epub, .docx, .txt)
   - More than 2 literature titles named in the answer (at most 1-2, named naturally in prose)

3. HOTLINE DISCIPLINE:
   If crisis_adjacent is false and the answer mentions 911, hotlines, crisis lines, or "call now" — FAIL.
   If crisis_adjacent is true, always PASS (hotlines are appropriate).

4. REGISTER FIT:
   FAIL if register is "brief" and the answer exceeds 4 sentences.
   FAIL if register is "reflective" and the answer does NOT contain a question (no "?" anywhere).
   FAIL if register is "factual" and the answer leads with a preamble ("That's a great question", "I understand", "Thank you for asking", restating the question, etc.) instead of the key information.
   PASS for "warm" (no structural rule).

5. REFUSAL CORRECTNESS:
   If sample_type is "refusal": FAIL if the answer does NOT decline to answer AND redirect (both required).
   If sample_type is "no_context": FAIL if the answer hallucinates specific literature citations, quotes fake passages, or invents titles not in the provided context.
   Otherwise SKIP.

CRITICAL NOTES:
- You are evaluating the ASSISTANT's answer in the conversation, not the user's question.
- For grounded: the user message contains the gold passages. The assistant should draw from them.
- For voice: "my sponsor" used generically ("they should talk to their sponsor") is OK. "my sponsor taught me..." is fake lived experience and FAIL.
- When in doubt, PASS. Only FAIL on clear violations."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_samples() -> list[dict]:
    """Load all samples from sft.jsonl."""
    samples = []
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def load_checkpoint() -> dict[str, Any]:
    """Load existing checkpoint if present."""
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {"processed_up_to": -1, "verdicts": []}


def save_checkpoint(processed_up_to: int, verdicts: list[dict]) -> None:
    """Save checkpoint atomically via tmpfile."""
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    data = {"processed_up_to": processed_up_to, "verdicts": verdicts}
    with open(tmp, "w") as f:
        json.dump(data, f)
    tmp.rename(CHECKPOINT_PATH)


def build_judge_messages(sample: dict) -> list[dict]:
    """Build the judge conversation for one sample."""
    meta = sample["meta"]
    messages = sample["messages"]
    user_msg = messages[1]["content"]
    asst_msg = messages[2]["content"]

    # Construct descriptive context for the judge
    meta_info = (
        f"SAMPLE TYPE: {meta.get('sample_type', '?')}\n"
        f"REGISTER: {meta.get('register', '?')}\n"
        f"CRISIS_ADJACENT: {meta.get('crisis_adjacent', False)}\n"
        f"GOLD_BLOCKS: {len(meta.get('gold_blocks', []))}\n"
        f"INTENT: {meta.get('intent_id', '?')}\n"
    )

    user_prompt = (
        f"{meta_info}\n"
        f"--- USER QUESTION (as seen by assistant) ---\n"
        f"{user_msg}\n\n"
        f"--- ASSISTANT ANSWER ---\n"
        f"{asst_msg}\n\n"
        f"--- EVALUATION ---\n"
        f"Rate each criterion PASS or FAIL per the rubric. "
        f"Respond with JSON only."
    )

    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def call_judge(client: OpenAI, sample: dict, idx: int) -> dict | None:
    """Call the dsv4 judge for one sample. Returns parsed verdict dict or None on fatal error."""
    messages = build_judge_messages(sample)

    for attempt in range(RETRY_LIMIT):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=512,
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            text = resp.choices[0].message.content.strip()

            # Extract JSON from potential wrapping
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            verdict = json.loads(text)

            # Validate required keys
            required = ["grounded", "voice", "hotline_discipline",
                        "register_fit", "refusal_correctness", "overall"]
            for k in required:
                if k not in verdict:
                    raise ValueError(f"Missing key '{k}' in judge response")

            return verdict

        except json.JSONDecodeError as e:
            if attempt < RETRY_LIMIT - 1:
                time.sleep(1)
                continue
            print(f"  [WARN] idx={idx}: JSON parse error after {RETRY_LIMIT} attempts: {e}", flush=True)
            print(f"  Raw text: {text[:300]}", flush=True)
            return None

        except Exception as e:
            if attempt < RETRY_LIMIT - 1:
                time.sleep(2)
                continue
            print(f"  [WARN] idx={idx}: API error after {RETRY_LIMIT} attempts: {e}", flush=True)
            return None


def judge_sample(client: OpenAI, sample: dict, idx: int) -> dict:
    """Judge one sample. Returns verdict dict with index."""
    verdict = call_judge(client, sample, idx)

    if verdict is None:
        # On fatal error, keep the sample (don't silently drop) but flag it
        return {
            "idx": idx,
            "intent_id": sample["meta"].get("intent_id", "?"),
            "register": sample["meta"].get("register", "?"),
            "sample_type": sample["meta"].get("sample_type", "?"),
            "overall": "KEEP",  # conservative: keep on error
            "drop_reason": "",
            "judge_error": True,
            "verdict": verdict,
        }

    # Determine if we should drop
    failures = []
    axes = [
        ("grounded", verdict.get("grounded", "PASS")),
        ("voice", verdict.get("voice", "PASS")),
        ("hotline_discipline", verdict.get("hotline_discipline", "PASS")),
        ("register_fit", verdict.get("register_fit", "PASS")),
        ("refusal_correctness", verdict.get("refusal_correctness", "PASS")),
    ]
    for axis_name, result in axes:
        if result == "FAIL":
            failures.append(axis_name)

    overall = verdict.get("overall", "KEEP")
    drop_reason = verdict.get("drop_reason", "")

    # If rubric says FAIL but overall KEEP, trust the rubric
    if failures and overall == "KEEP":
        overall = "DROP"
        drop_reason = "; ".join(failures)

    return {
        "idx": idx,
        "intent_id": sample["meta"].get("intent_id", "?"),
        "register": sample["meta"].get("register", "?"),
        "sample_type": sample["meta"].get("sample_type", "?"),
        "crisis_adjacent": sample["meta"].get("crisis_adjacent", False),
        "overall": overall,
        "drop_reason": drop_reason or (failures[0] if failures else ""),
        "judge_error": False,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60, flush=True)
    print("FT-C3: Quality filter", flush=True)
    print("=" * 60, flush=True)

    # Load input
    samples = load_samples()
    print(f"Loaded {len(samples)} samples from {INPUT_PATH}", flush=True)

    # Load checkpoint
    ckpt = load_checkpoint()
    processed_up_to = ckpt["processed_up_to"]
    verdicts: list[dict] = ckpt.get("verdicts", [])
    print(f"Checkpoint: processed up to index {processed_up_to}", flush=True)

    # Determine remaining indices
    start_idx = processed_up_to + 1
    if start_idx >= len(samples):
        print("All samples already processed. Rebuilding output from verdicts.", flush=True)
    else:
        print(f"Processing indices {start_idx} to {len(samples) - 1} ({len(samples) - start_idx} remaining)", flush=True)

    # Initialize OpenAI client
    client = OpenAI(base_url=LLM_BASE_URL, api_key="none", max_retries=0)

    # Process remaining samples
    if start_idx < len(samples):
        indices = list(range(start_idx, len(samples)))
        completed = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
            future_map = {}
            for idx in indices:
                future = executor.submit(judge_sample, client, samples[idx], idx)
                future_map[future] = idx

            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    result = future.result()
                    verdicts.append(result)
                    completed += 1
                    if result.get("judge_error"):
                        errors += 1
                except Exception as e:
                    print(f"  [ERROR] idx={idx}: unexpected error: {e}", flush=True)
                    traceback.print_exc()
                    # Keep on error
                    verdicts.append({
                        "idx": idx,
                        "intent_id": samples[idx]["meta"].get("intent_id", "?"),
                        "register": samples[idx]["meta"].get("register", "?"),
                        "sample_type": samples[idx]["meta"].get("sample_type", "?"),
                        "overall": "KEEP",
                        "drop_reason": "",
                        "judge_error": True,
                        "verdict": None,
                    })
                    completed += 1
                    errors += 1

                # Checkpoint periodically
                if completed > 0 and completed % BATCH_SIZE == 0:
                    last_processed = max(v["idx"] for v in verdicts)
                    save_checkpoint(last_processed, verdicts)
                    kept = sum(1 for v in verdicts if v["overall"] == "KEEP")
                    dropped = sum(1 for v in verdicts if v["overall"] == "DROP")
                    print(f"  Progress: {completed}/{len(indices)} judged, "
                          f"{kept} kept, {dropped} dropped, {errors} errors", flush=True)

        # Final checkpoint
        if verdicts:
            last_processed = max(v["idx"] for v in verdicts)
            save_checkpoint(last_processed, verdicts)

        print(f"\nDone judging. {completed} samples processed ({errors} errors)", flush=True)

    # Sort verdicts by index
    verdicts.sort(key=lambda v: v["idx"])

    # --- Build filtered output ---
    kept_samples = []
    dropped_samples = []
    for v in verdicts:
        if v["overall"] == "KEEP":
            kept_samples.append(samples[v["idx"]])
        else:
            dropped_samples.append({
                "idx": v["idx"],
                "intent_id": v["intent_id"],
                "register": v["register"],
                "sample_type": v["sample_type"],
                "drop_reason": v["drop_reason"],
            })

    # Write filtered JSONL
    with open(OUTPUT_PATH, "w") as f:
        for s in kept_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(kept_samples)} kept samples to {OUTPUT_PATH}", flush=True)

    # --- Build report ---
    total = len(samples)
    kept = len(kept_samples)
    dropped = total - kept

    # By intent
    intent_drops: dict[str, int] = {}
    intent_totals: dict[str, int] = {}
    for v in verdicts:
        iid = v["intent_id"]
        intent_totals[iid] = intent_totals.get(iid, 0) + 1
        if v["overall"] == "DROP":
            intent_drops[iid] = intent_drops.get(iid, 0) + 1

    intent_report = {}
    for iid in sorted(intent_totals):
        ti = intent_totals[iid]
        di = intent_drops.get(iid, 0)
        intent_report[iid] = {
            "total": ti,
            "kept": ti - di,
            "dropped": di,
            "drop_rate": round(di / ti, 4) if ti > 0 else 0,
        }

    # By rubric reason
    reason_counts: dict[str, int] = {}
    for v in verdicts:
        if v["overall"] == "DROP" and v["drop_reason"]:
            # Split multiple reasons
            reasons = v["drop_reason"].split("; ")
            for r in reasons:
                r = r.strip()
                if r:
                    reason_counts[r] = reason_counts.get(r, 0) + 1

    report = {
        "total": total,
        "kept": kept,
        "dropped": dropped,
        "drop_rate": round(dropped / total, 4) if total > 0 else 0,
        "judge_errors": sum(1 for v in verdicts if v.get("judge_error")),
        "by_intent": intent_report,
        "by_reason": reason_counts,
        "intent_counts": len(intent_totals),
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Wrote report to {REPORT_PATH}", flush=True)

    # Print summary
    print(f"\n{'='*60}", flush=True)
    print(f"SUMMARY", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Total samples: {total}", flush=True)
    print(f"  Kept:          {kept}", flush=True)
    print(f"  Dropped:       {dropped}", flush=True)
    print(f"  Drop rate:     {dropped/max(total,1):.2%}", flush=True)
    print(f"  Judge errors:  {report['judge_errors']}", flush=True)
    print(f"  By reason:     {json.dumps(reason_counts, indent=2)}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
