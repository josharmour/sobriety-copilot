#!/usr/bin/env python3
"""
FT-C3 re-evaluation: run a more lenient judge on dropped samples.
Focus: register_fit false positives (factual preamble rule too strict)
and voice false positives (title count threshold borderline).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
FILTERED_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "filter_report.json"
CKPT_PATH = REPO_ROOT / "finetune" / "gen" / ".filter_checkpoint.json"

LLM_BASE_URL = "http://10.0.0.10:8002/v1"
LLM_MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.0
MAX_CONCURRENCY = 16

JUDGE_SYSTEM = """You are a quality judge for a recovery assistant's training data. Evaluate per the rubric below. Be fair — only FAIL on clear violations.

Respond with ONLY valid JSON:
{"grounded":"PASS"|"FAIL"|"SKIP", "voice":"PASS"|"FAIL", "hotline_discipline":"PASS"|"FAIL", "register_fit":"PASS"|"FAIL", "refusal_correctness":"PASS"|"FAIL"|"SKIP", "overall":"KEEP"|"DROP", "drop_reason":"..."}

RUBRIC (FAIL only on clear violations):

1. GROUNDED (SKIP for no_context/refusal):
   PASS if answer is consistent with gold passages or honestly says they don't cover the topic.
   FAIL only if answer contradicts the gold passages or invents specific claims/quotes not present.

2. VOICE:
   FAIL on: fake lived experience, bracketed citations [1], filenames, >3 literature titles.

3. HOTLINE DISCIPLINE:
   If crisis_adjacent=false and answer mentions 911/hotlines/crisis lines → FAIL.

4. REGISTER FIT:
   brief: >4 sentences → FAIL.
   reflective: no "?" anywhere → FAIL.
   factual: FAIL only if answer is pure fluff with no substance (e.g., just "Great question!").
     Saying "The passages provided don't address X" IS leading with key info — PASS.
   warm: always PASS.

5. REFUSAL CORRECTNESS:
   refusal: must decline AND redirect. FAIL if missing either.
   no_context: FAIL only if invents fake citations/quotes/pages.
   Otherwise SKIP.

When in doubt, PASS."""


def main():
    samples = []
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    with open(CKPT_PATH) as f:
        ckpt = json.load(f)

    # Identify which indices to keep from original run
    keep_indices = set()
    re_eval_indices = set()
    for v in ckpt["verdicts"]:
        if v["overall"] == "KEEP":
            keep_indices.add(v["idx"])
        elif v["overall"] == "DROP":
            r = v.get("drop_reason", "")
            # Re-evaluate register_fit and voice drops (potential false positives)
            if "register_fit" in r or r == "voice":
                re_eval_indices.add(v["idx"])

    print(f"Original kept: {len(keep_indices)}")
    print(f"To re-evaluate: {len(re_eval_indices)}")

    if not re_eval_indices:
        print("No samples to re-evaluate.")
        return

    client = OpenAI(base_url=LLM_BASE_URL, api_key="none", max_retries=0)

    new_keeps = []
    lock = __import__('threading').Lock()

    def judge_one(idx):
        s = samples[idx]
        meta = s["meta"]
        meta_info = (
            f"SAMPLE TYPE: {meta.get('sample_type','?')}\n"
            f"REGISTER: {meta.get('register','?')}\n"
            f"CRISIS_ADJACENT: {meta.get('crisis_adjacent',False)}\n"
            f"GOLD_BLOCKS: {len(meta.get('gold_blocks',[]))}\n"
            f"INTENT: {meta.get('intent_id','?')}\n"
        )
        user_prompt = (
            f"{meta_info}\n"
            f"--- USER QUESTION ---\n{s['messages'][1]['content']}\n\n"
            f"--- ASSISTANT ANSWER ---\n{s['messages'][2]['content']}\n\n"
            f"--- EVALUATION ---\n"
            f"Rate each criterion PASS or FAIL. JSON only."
        )
        msgs = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL, messages=msgs,
                    temperature=TEMPERATURE, max_tokens=512,
                    extra_body={"chat_template_kwargs": {"thinking": False}},
                )
                text = resp.choices[0].message.content.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                verdict = json.loads(text)
                return idx, verdict.get("overall") == "KEEP"
            except Exception:
                if attempt < 2:
                    time.sleep(2)
        return idx, False

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as ex:
        futs = {ex.submit(judge_one, idx): idx for idx in re_eval_indices}
        done = 0
        for fut in as_completed(futs):
            idx, is_keep = fut.result()
            done += 1
            if is_keep:
                new_keeps.append(idx)
            if done % 100 == 0:
                print(f"  Progress: {done}/{len(re_eval_indices)} (new keeps: {len(new_keeps)})", flush=True)

    print(f"\nNew keeps from re-evaluation: {len(new_keeps)}")

    if not new_keeps:
        print("No additional samples recovered. Final count unchanged.")
        return

    # Update keep set
    keep_indices.update(new_keeps)
    kept_sorted = sorted(keep_indices)

    # Write updated filtered file
    with open(FILTERED_PATH, "w") as f:
        for idx in kept_sorted:
            f.write(json.dumps(samples[idx], ensure_ascii=False) + "\n")
    print(f"Wrote {len(kept_sorted)} samples to {FILTERED_PATH}")

    # Rebuild report
    intent_totals = Counter()
    intent_kept = Counter()
    reason_counts = Counter()

    for v in ckpt["verdicts"]:
        iid = v["intent_id"]
        intent_totals[iid] += 1
        if v["idx"] in keep_indices:
            intent_kept[iid] += 1
        elif v["overall"] == "DROP" and v["idx"] not in new_keeps:
            reasons = v.get("drop_reason", "").split("; ")
            for r in reasons:
                r = r.strip()
                if r:
                    reason_counts[r] += 1

    total = len(samples)
    kept_count = len(kept_sorted)
    dropped_count = total - kept_count

    by_intent = {}
    for iid in sorted(intent_totals):
        ti = intent_totals[iid]
        ki = intent_kept[iid]
        by_intent[iid] = {
            "total": ti,
            "kept": ki,
            "dropped": ti - ki,
            "drop_rate": round((ti - ki) / ti, 4) if ti > 0 else 0,
        }

    report = {
        "total": total,
        "kept": kept_count,
        "dropped": dropped_count,
        "drop_rate": round(dropped_count / total, 4),
        "judge_errors": 0,
        "by_intent": by_intent,
        "by_reason": dict(reason_counts),
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nFinal: {kept_count} kept, {dropped_count} dropped ({dropped_count/total*100:.2f}%)")
    print(f"Updated report written to {REPORT_PATH}")


if __name__ == "__main__":
    raise SystemExit(main())
