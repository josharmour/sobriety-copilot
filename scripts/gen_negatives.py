#!/usr/bin/env python3
"""Replace off-topic negative questions with curated recovery-adjacent ones.
Fast — no API calls needed."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
Q_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"

RECOVERY_LEXICON = [
    'alcohol', 'drink', 'sober', 'recovery', 'addict', 'drug', 'AA', 'NA',
    'step', 'meeting', 'sponsor', 'rehab', 'relapse', 'detox', 'withdrawal',
    'DUI', 'naltrexone', 'twelve', 'program', 'addiction', 'sobriety',
    'clean', 'substance', 'fellowship', 'amends', 'inventory',
    'higher power', 'surrender', 'powerless', 'serenity', 'vivitrol',
    'suboxone', 'methadone', 'outpatient', 'inpatient', 'dual diagnosis',
]

# Curated negative questions — all recovery-adjacent but unanswered by corpus
# Category distribution:
#   Medical/clinical: 12
#   Legal: 6
#   Statistics/programs: 6
#   Logistics/policy: 6
#   Other-recovery: 6
#   Fully off-topic (sanity anchors): 4
# Total: 40
CURATED_NEGATIVES = [
    # Medical/clinical (12)
    "What is the recommended starting dosage of naltrexone for alcohol use disorder?",
    "How often should Vivitrol injections be administered for opioid maintenance treatment?",
    "What is the standard prescription protocol for Antabuse (disulfiram) for alcohol dependence?",
    "Does health insurance typically cover inpatient detox and rehabilitation programs?",
    "What is the standard medical protocol for managing alcohol withdrawal syndrome?",
    "Which is more effective for alcohol relapse prevention: naltrexone or acamprosate?",
    "What is the Suboxone induction protocol for opioid use disorder treatment?",
    "What are the federal regulations for methadone clinic dosing and attendance?",
    "How does The Sinclair Method differ from abstinence-based approaches?",
    "What are the best treatment protocols for patients with dual diagnosis?",
    "Is medication-assisted treatment considered safe during pregnancy for opioid use disorder?",
    "What are the CDC guidelines for prescribing benzodiazepines to patients in recovery?",

    # Legal (6)
    "What are the steps to get a DUI expunged from my criminal record?",
    "What are the requirements for getting a court card signed at an AA meeting?",
    "Is court-mandated AA attendance considered constitutional under the First Amendment?",
    "What are typical probation conditions for a first-time DUI offense?",
    "Does the Americans with Disabilities Act protect people with a history of substance use disorder?",
    "What are the state licensing requirements to become a certified addiction counselor?",

    # Statistics / program comparisons (6)
    "What percentage of AA members maintain sobriety after one year according to peer-reviewed studies?",
    "How does the effectiveness of SMART Recovery compare to 12-step facilitation therapy?",
    "What is the history and philosophy of Rational Recovery as an alternative to AA?",
    "How does LifeRing secular recovery differ from traditional 12-step programs?",
    "How does CBT compare to 12-step facilitation therapy in treating substance use disorders?",
    "What does research say about harm reduction versus abstinence-based treatment outcomes?",

    # Logistics / policy (6)
    "Can my employer fire me for entering a substance abuse treatment program?",
    "Am I eligible for FMLA leave to attend an inpatient rehabilitation program?",
    "How do I file an insurance claim for outpatient addiction treatment services?",
    "What are the federal regulations for prescribing controlled substances in addiction treatment?",
    "What LGBTQ+ specific recovery programs and resources are available in the United States?",
    "What are the best practices for treating co-occurring PTSD and substance use disorder?",

    # Other recovery approaches (6)
    "What is the evidence behind the Sinclair Method for alcohol use disorder?",
    "How do faith-based treatment programs compare to secular programs in long-term outcomes?",
    "What is patient brokering and why is it considered unethical in the rehab industry?",
    "What are the recommended approaches for treating adolescent substance use disorder?",
    "How prevalent is alcohol abuse in the elderly population and what treatments are recommended?",
    "What does genetic research say about hereditary predisposition to alcoholism?",

    # Sanity anchors — fully off-topic (4)
    "How often should I flush the sediment from my water heater to maintain efficiency?",
    "What is the best method for removing red wine stains from a white cotton shirt?",
    "How do I reset a forgotten BIOS password on a Dell laptop without removing the CMOS battery?",
    "What is the proper way to sharpen a chef's knife using a whetstone?",
]


def main():
    with open(Q_PATH) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(rows)} rows", flush=True)
    kinds = Counter(r["kind"] for r in rows)
    for k, c in sorted(kinds.items()):
        print(f"  {k}: {c}", flush=True)

    # Find off-topic negatives
    neg_rows = [(i, r) for i, r in enumerate(rows) if r["kind"] == "negative"]
    offtopic = [(i, r) for i, r in neg_rows
                 if not any(kw in r["question"].lower() for kw in RECOVERY_LEXICON)]

    print(f"\nOff-topic negatives: {len(offtopic)}/{len(neg_rows)}", flush=True)

    if len(offtopic) > len(CURATED_NEGATIVES):
        print(f"WARNING: only {len(CURATED_NEGATIVES)} curated questions available "
              f"but {len(offtopic)} needed", file=sys.stderr, flush=True)

    fixed = 0
    for idx, (i, row) in enumerate(offtopic):
        if idx >= len(CURATED_NEGATIVES):
            break
        new_q = CURATED_NEGATIVES[idx]
        rows[i]["question"] = new_q
        fixed += 1
        print(f"  {row['id']}: {new_q[:100]}", flush=True)

    # Save
    with open(Q_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Verify
    final_negs = [r for r in rows if r["kind"] == "negative"]
    final_offtopic = [r for r in final_negs
                       if not any(kw in r["question"].lower() for kw in RECOVERY_LEXICON)]

    print(f"\n{'='*60}", flush=True)
    print(f"Fixed: {fixed} negatives", flush=True)
    print(f"Off-topic remaining: {len(final_offtopic)}/{len(final_negs)}", flush=True)
    for r in final_offtopic:
        print(f"  OFFTOPIC: {r['id']}: {r['question'][:120]}", flush=True)

    # Check for duplicates
    qs = [r["question"] for r in final_negs]
    dupes = len(qs) - len(set(qs))
    if dupes:
        print(f"WARNING: {dupes} duplicate questions!", file=sys.stderr, flush=True)

    if len(final_offtopic) > 5:
        print("FAIL: too many off-topic negatives", file=sys.stderr, flush=True)
        return 1

    print("ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
