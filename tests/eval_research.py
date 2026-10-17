"""Depth score for research mode: questions whose answers are computed from the text itself.

Every expected answer is derived from the manifests at run time (exact counts,
whether a phrase really occurs, which chapter holds a passage), so the score
can't drift from the books. Each case is sent to /api/research; the score is
the share answered correctly, plus how many of the answers' quotes and page
citations the server could verify.

    python -m tests.eval_research                       # http://localhost:5000
    python -m tests.eval_research --base-url http://10.0.0.100:5077
    python -m tests.eval_research --only count          # one family

Writes tests/eval_research_results.json (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.research.library import Library  # noqa: E402

BIG_BOOK = "alcoholics-anonymous"
TWELVE = "twelve-steps-and-twelve-traditions"

COUNTS = [  # (book, section title, term, how to ask)
    (BIG_BOOK, "Into Action", "pray*", "words beginning with “pray” (pray, prayer, prayed, praying)"),
    (BIG_BOOK, "How It Works", "resent*", "words beginning with “resent” (resent, resentment, resentful…)"),
    (BIG_BOOK, "We Agnostics", "faith", "the word “faith”"),
    (TWELVE, "Step Eleven", "meditat*", "words beginning with “meditat” (meditate, meditation…)"),
    (TWELVE, "Tradition Twelve", "anonymity", "the word “anonymity”"),
]
PRESENCE = [  # (book, phrase) — expected yes/no is computed
    (BIG_BOOK, "let go and let god"),
    (BIG_BOOK, "one day at a time"),
    (BIG_BOOK, "god grant me the serenity"),
    (BIG_BOOK, "fake it till you make it"),
    (BIG_BOOK, "restless, irritable and discontented"),
    (TWELVE, "god grant me the serenity"),
]
LOCATIONS = [  # (book, exact words) — expected chapter is computed
    (BIG_BOOK, "God, I offer myself to Thee"),
    (BIG_BOOK, "My Creator, I am now willing that you should have all of me"),
    (BIG_BOOK, "Rarely have we seen a person fail"),
    (TWELVE, "Lord, make me a channel of thy peace"),
    (BIG_BOOK, "We will intuitively know how to handle situations"),
]


def build_cases(lib: Library) -> list[dict]:
    cases = []
    for doc, sec, term, spoken in COUNTS:
        book = lib.book(doc)
        n = lib.resolve_section(book, sec)
        expected = lib.find([term], [doc], n)["totals"].get(term, 0)
        cases.append({"family": "count", "q": f"In {book.info.title}, chapter “{sec}”, exactly how many times do "
                      f"{spoken} appear?", "expect": expected})
    for doc, phrase in PRESENCE:
        book = lib.book(doc)
        found = lib.find([phrase], [doc])["totals"].get(phrase, 0) > 0
        cases.append({"family": "presence", "q": f"Does the exact phrase “{phrase}” appear anywhere in "
                      f"{book.info.title}? Answer yes or no first.", "expect": found})
    for doc, words in LOCATIONS:
        book = lib.book(doc)
        hit = lib.find([words], [doc])["quotes"]
        sec = book.outline[hit[0]["block"].section].title if hit and hit[0]["block"].section is not None else None
        cases.append({"family": "location", "q": f"Which chapter of {book.info.title} contains the words "
                      f"“{words}”?", "expect": sec})
    return [c for c in cases if c["expect"] is not None]


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                 "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three").split()


def grade(case: dict, answer: str) -> bool:
    a = answer.lower()
    if case["family"] == "count":
        head = a[:400]
        word = _NUMBER_WORDS[case["expect"]] if case["expect"] < len(_NUMBER_WORDS) else None
        return bool(re.search(rf"\b{case['expect']}\b", head)) or bool(word and re.search(rf"\b{word}\b", head)) or (
            case["expect"] == 0 and re.search(r"\b(zero|none|no occurrences|does not appear)\b", head) is not None)
    if case["family"] == "presence":
        head = re.sub(r"[*_#>]", "", a[:160]).strip()
        says_no = bool(re.match(r"^(no\b|not\b|it does not|the exact phrase .{0,60} does not)", head)) or \
            " does not appear" in head[:120]
        return says_no != case["expect"]
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower().replace("’", "'")).strip()  # noqa: E731
    return norm(case["expect"]) in norm(answer)


def ask(base: str, q: str, timeout: int = 600) -> tuple[str, dict | None, float]:
    req = urllib.request.Request(f"{base}/api/research", json.dumps({"message": q, "tone": "factual"}).encode(),
                                 {"Content-Type": "application/json", "Accept": "text/event-stream",
                                  "User-Agent": "curl/8 eval_research"})
    t0 = time.monotonic()
    answer, check = [], None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if "token" in ev:
                answer.append(ev["token"])
            elif ev.get("research", {}).get("type") == "verification":
                check = ev["research"]
            elif "error" in ev:
                raise RuntimeError(ev["error"])
    return "".join(answer), check, time.monotonic() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("RESEARCH_BASE_URL", "http://localhost:5000"))
    ap.add_argument("--only", choices=["count", "presence", "location"])
    args = ap.parse_args()
    cases = [c for c in build_cases(Library(os.path.join(ROOT, "documents"))) if not args.only or c["family"] == args.only]
    results, quotes, verified = [], 0, 0
    for c in cases:
        try:
            answer, check, secs = ask(args.base_url.rstrip("/"), c["q"])
            ok = grade(c, answer)
        except Exception as exc:
            answer, check, secs, ok = f"ERROR {exc}", None, 0.0, False
        if check:
            quotes += check.get("quotes", 0)
            verified += check.get("quotes_verified", 0)
        results.append({**c, "ok": ok, "seconds": round(secs, 1), "check": check, "answer": answer})
        print(f"[{'PASS' if ok else 'FAIL'}] {c['family']:8s} expect={c['expect']!s:24s} {secs:5.1f}s  {c['q'][:70]}", flush=True)
    passed = sum(r["ok"] for r in results)
    print(f"\ndepth score: {passed}/{len(results)} correct"
          + (f"; quotes verified {verified}/{quotes}" if quotes else ""))
    out = os.path.join(ROOT, "tests", "eval_research_results.json")
    json.dump(results, open(out, "w"), indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
