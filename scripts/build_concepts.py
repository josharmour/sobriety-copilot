#!/usr/bin/env python3
"""Mine the literature for the knowledge graph's concepts (offline, one-time per corpus).

Stage 1  mine   — candidate phrases from every manifest: distinctive words,
                  collocations ("bondage of self"), proper names ("Oxford
                  Group"), and sayings repeated in quotation marks ("Easy Does
                  It"). Pure statistics, no model.
Stage 2  curate — the LLM keeps the meaningful ones and gives each a clean
                  label, a type and a home topic (one of graph_taxonomy's hubs);
         dedupe — labels naming the same person/thing/idea are merged.
Stage 3  layout — co-occurrence across passages → prominence (PageRank) and a
                  2-D map position for every concept and hub.

Output: src/rag/data/graph_concepts.json (committed; the server only loads it).

    python scripts/build_concepts.py mine            # → scratch candidates file
    python scripts/build_concepts.py curate          # needs LLM_BASE_URL / LLM_API_KEY
    python scripts/build_concepts.py dedupe          # merge labels naming the same thing
    python scripts/build_concepts.py layout          # writes graph_concepts.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.rag.concept_text import STOPWORDS, passages_for_book, tokens  # noqa: E402
from src.rag.graph_taxonomy import GROUPS, TOPICS  # noqa: E402
from src.research.library import Library  # noqa: E402

DOCS = os.path.join(ROOT, "documents")
WORK = os.environ.get("CONCEPTS_WORKDIR", os.path.join(ROOT, "scratch", "concepts"))
OUT = os.path.join(ROOT, "src", "rag", "data", "graph_concepts.json")

# Words that make a phrase generic however often it occurs.
GENERIC = set("""
time times day days year years week weeks month months thing things way ways lot lots kind kinds sort part
parts people person man men woman women one ones life lives world place places end start beginning point
first second last next new old good bad great little big long short much many more most less least other
others same different whole own able really just even still also ever never always often sometimes
something anything everything nothing someone anyone everyone nobody somebody anybody everybody
got get gets getting go goes going went gone come comes coming came make makes making made take takes
taking took say says said tell tells told know knows knew known think thinks thought see sees saw seen
want wants wanted look looks looked feel felt seem seemed find found give gave given put keep kept let
use used try tried work worked call called ask asked need needed mean means meant begin began become
became may might must shall would could should will can cannot couldn't wouldn't didn't don't doesn't
isn't wasn't weren't aren't haven't hasn't hadn't i'm i've i'd i'll you're we're they're it's that's
there's what's he's she's let's mr mrs ms page pages chapter chapters book books copyright inc press
edition printed rights reserved isbn www com org fig figure table contents index
""".split())


# ── Stage 1: mine ─────────────────────────────────────────────────────────


def mine(lib: Library) -> list[dict]:
    uni: Counter = Counter()
    uni_books: dict[str, set] = defaultdict(set)
    ngram: Counter = Counter()
    ngram_books: dict[str, set] = defaultdict(set)
    proper: Counter = Counter()
    proper_books: dict[str, set] = defaultdict(set)
    saying: Counter = Counter()
    saying_books: dict[str, set] = defaultdict(set)
    total_tokens = 0
    t0 = time.time()
    cap_seq = re.compile(r"(?<![.!?:;“\"]\s)(?<!^)\b((?:(?:Dr|St|Mr|Mrs)\.\s)?[A-Z][a-z’']+(?:\s(?:of|the|and|de|von)\s[A-Z][a-z’']+|\s[A-Z][a-z’']+|\s[A-Z]\.){0,3})")
    quoted = re.compile(r"[“\"]([A-Z][^”\"]{6,60}?)[.!,]?[”\"]")
    for doc_id, info in lib.catalog().items():
        book = lib.book(doc_id)
        for p in passages_for_book(book):
            toks = tokens(p.text)
            total_tokens += len(toks)
            for t in toks:
                uni[t] += 1
                uni_books[t].add(doc_id)
            for n in (2, 3, 4):
                for i in range(len(toks) - n + 1):
                    g = toks[i:i + n]
                    if g[0] in STOPWORDS or g[-1] in STOPWORDS:
                        continue
                    if n >= 3 and sum(w in STOPWORDS for w in g) > n - 2:
                        continue
                    key = " ".join(g)
                    ngram[key] += 1
                    ngram_books[key].add(doc_id)
            for m in cap_seq.finditer(p.text):
                name = m.group(1).strip()
                if len(name) < 4 or name.lower() in STOPWORDS:
                    continue
                proper[name] += 1
                proper_books[name].add(doc_id)
            for m in quoted.finditer(p.text):
                s = m.group(1).strip()
                if 2 <= len(s.split()) <= 8:
                    k = s.lower().rstrip(".!,")
                    saying[k] += 1
                    saying_books[k].add(doc_id)
        print(f"  mined {doc_id} ({time.time() - t0:.0f}s)", flush=True)

    cands: dict[str, dict] = {}

    def add(key: str, label: str, kind: str, count: int, books: int, score: float) -> None:
        k = key.lower()
        if k in cands and cands[k]["score"] >= score:
            return
        cands[k] = {"key": k, "label": label, "kind": kind, "count": count, "books": books, "score": round(score, 3)}

    for w, c in uni.items():
        nb = len(uni_books[w])
        if c < 25 or nb < 4 or w in STOPWORDS or w in GENERIC or len(w) < 4 or not w.isalpha():
            continue
        # Prefer words that are dense in some books and absent in others (distinctive).
        disp = nb / len(lib.catalog())
        add(w, w, "word", c, nb, math.log(c) * math.log(1 + nb) * (1.2 - disp))
    for g, c in ngram.items():
        nb = len(ngram_books[g])
        if c < 8 or (nb < 2 and c < 20):
            continue
        words = g.split()
        content = [w for w in words if w not in STOPWORDS and w not in GENERIC]
        if not content or all(w in GENERIC or w in STOPWORDS for w in (words[0], words[-1])):
            continue
        # Association: how much more often the words occur together than apart.
        expected = total_tokens
        for w in words:
            expected *= uni[w] / total_tokens
        pmi = math.log(c / max(expected, 1e-9))
        if pmi < 3.0:
            continue
        add(g, g, "phrase", c, nb, math.log(c) * math.log(1 + nb) * min(pmi, 12) / 4)
    for name, c in proper.items():
        nb = len(proper_books[name])
        if c < 6 or (nb < 2 and c < 15):
            continue
        if name.split()[0].lower() in STOPWORDS:
            continue
        add(name.lower(), name, "name", c, nb, math.log(c) * math.log(1 + nb) * 1.3)
    for s, c in saying.items():
        nb = len(saying_books[s])
        if c < 4 or nb < 2:
            continue
        add(s, s.capitalize(), "saying", c, nb, math.log(c) * math.log(1 + nb) * 1.5)

    # Drop fragments of a longer candidate that occurs nearly as often
    # ("understood him" inside "god as we understood him").
    keys = sorted(cands, key=lambda k: -len(k.split()))
    for long in keys:
        lw = long.split()
        if len(lw) < 3 or long not in cands:
            continue
        for n in range(2, len(lw)):
            for i in range(len(lw) - n + 1):
                frag = " ".join(lw[i:i + n])
                f = cands.get(frag)
                if f and f["kind"] == "phrase" and cands[long]["count"] >= 0.8 * f["count"]:
                    del cands[frag]
    out = sorted(cands.values(), key=lambda c: -c["score"])
    print(f"mined {len(out)} candidates from {total_tokens:,} tokens in {time.time() - t0:.0f}s", flush=True)
    return out


# ── Stage 2: curate ───────────────────────────────────────────────────────

_MONTHS_DAYS = set("""january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday""".split())
_QUOTAS = {"word": 0.38, "phrase": 0.50, "name": 0.11, "saying": 0.01}


def _junk(c: dict) -> bool:
    k = c["key"]
    if re.search(r"\d", k) or re.search(r"\b(?:ibid|doi|pp?|vol|ed|eds|isbn|www|http)\b", k):
        return True
    if c["kind"] == "name" and (re.search(r"[’'](?:ve|ll|s|t|re|d|m)$", k) or k in _MONTHS_DAYS):
        return True
    return False


def select_for_curation(cands: list[dict], limit: int) -> list[dict]:
    """The best candidates of each kind, so names and sayings aren't crowded out by words."""
    out = []
    for kind, share in _QUOTAS.items():
        pool = [c for c in cands if c["kind"] == kind and not _junk(c)]
        out.extend(pool[: max(int(limit * share), 1) if kind != "saying" else len(pool)])
    return sorted(out, key=lambda c: -c["score"])

_TYPES = ["concept", "emotion", "trait", "practice", "saying", "prayer", "person", "place", "organization",
          "text", "event", "substance", "condition"]
CURATE_PROMPT = """You are building the concept map of a library of recovery literature (A.A., N.A. and other \
12-step texts, plus books on addiction, shame, trauma, codependency and spirituality).
Each numbered phrase was mined statistically from the books (count, number of books). Return one item for EVERY \
number, in order.
- label: a clean display label in natural capitalisation, no parentheses. Variants share one label \
("resentments" -> "Resentment"). A fragment of the wording of a Step or Tradition gets exactly that Step's or \
Tradition's name ("remove our shortcomings" -> "Step Seven"; "desire to stop drinking" -> "Tradition Three"). A \
fragment of a longer well-known phrase gets the full phrase ("god as we understood" -> "God as we understood Him").
- keep: true if a reader would want it as a node on the map — a recovery or spiritual idea, emotion, character \
trait or defect, practice, slogan or saying, prayer, notable person, place, group or organization, book, event, \
substance or condition. false for generic phrases ("long time", "point of view", "two or three"), sentence \
fragments that aren't a recognisable idea, publishing boilerplate, OCR noise, and minor characters.
- type: the kind of thing it is.
- hub: the topic it belongs under (id from this list), or none:
{hubs}

Phrases:
{rows}"""


def curate(cands: list[dict], batch: int = 40) -> list[dict]:
    """LLM keep/label/type/hub for every candidate, via structured output (one item per phrase)."""
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ.get("LLM_API_KEY", ""), timeout=600)
    model = os.environ.get("LLM_MODEL", "dsv4")
    hub_ids = [t[0] for t in TOPICS] + ["none"]
    hub_text = "; ".join(f"{t[0]} = {t[1]}" for t in TOPICS)
    schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
        "type": "object", "required": ["n", "label", "keep", "type", "hub"], "properties": {
            "n": {"type": "integer"}, "label": {"type": "string", "minLength": 2}, "keep": {"type": "boolean"},
            "type": {"type": "string", "enum": _TYPES}, "hub": {"type": "string", "enum": hub_ids}}}}}}
    batches = [cands[i:i + batch] for i in range(0, len(cands), batch)]
    cache_path = os.path.join(WORK, "curated_batches.json")
    done: dict[str, list] = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    def run(i: int) -> tuple[int, list]:
        if str(i) in done:
            return i, done[str(i)]
        rows = batches[i]
        text = "\n".join(f"{n}. {r['label']} ({r['count']}, {r['books']})" for n, r in enumerate(rows))
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model, max_tokens=8000, temperature=0.2,
                    messages=[{"role": "user", "content": CURATE_PROMPT.format(hubs=hub_text, rows=text)}],
                    # Compact JSON: with free whitespace the model sometimes pads with
                    # newlines until it runs out of tokens.
                    extra_body={"structured_outputs": {"json": schema, "disable_any_whitespace": True},
                                "chat_template_kwargs": {"thinking": True, "reasoning_effort": "low"}, "priority": 5},
                )
                items = json.loads(resp.choices[0].message.content)["items"]
                return i, [{**rows[it["n"]], "label": it["label"].strip(), "type": it["type"],
                            "hub": None if it["hub"] == "none" else it["hub"]}
                           for it in items
                           if isinstance(it.get("n"), int) and 0 <= it["n"] < len(rows) and it.get("keep")]
            except Exception as exc:
                print(f"  batch {i} attempt {attempt + 1}: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(5)
        return i, []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, out in pool.map(run, range(len(batches))):
            done[str(i)] = out
            json.dump(done, open(cache_path, "w"))
            print(f"  batch {i + 1}/{len(batches)}: kept {len(out)}/{len(batches[i])} ({time.time() - t0:.0f}s)",
                  flush=True)
    return [x for i in range(len(batches)) for x in done.get(str(i), [])]


_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")
_STEP_NAME_RE = re.compile(r"\b(Step|Tradition)\s+(One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\b")


_COMMENTARY_RE = re.compile(r"\b(?:keep|generic|refers to|true|false|drop)\b", re.IGNORECASE)


def clean_label(label: str) -> str:
    """Strip quotes/parentheticals/commentary; a label that names a Step or Tradition becomes that name."""
    label = re.sub(r"\s+", " ", label.replace("\xa0", " ")).strip()
    # Second thoughts: "… Smithkoff? No—Co-Founders of A.A" keeps the correction.
    if "?" in label or "→" in label or " = " in label:
        if _STEP_NAME_RE.search(label):
            m = _STEP_NAME_RE.findall(label)[-1]
            return f"{m[0]} {m[1]}"
        label = re.split(r"No\s*[—-]|→|=", label)[-1]
    # The model sometimes explains itself inside the label:
    # "Step' — Generic Word but Refers to the Twelve Steps; Keep True as 'The Twelve Steps'."
    if " — " in label or ";" in label or _COMMENTARY_RE.search(label):
        quoted = re.findall(r"[‘'\"“]([^‘'\"“”’]{3,60})[’'\"”]", label)
        label = quoted[-1] if quoted else re.split(r" — |;", label)[0]
    label = label.strip().rstrip(".,;:·").strip("'\"“”‘’ ")
    named = _STEP_NAME_RE.search(label)
    base = _PAREN_RE.sub("", label).strip().strip("'\"“”‘’ ").strip()
    if named and (not base or named.start() >= len(base) or base.lower().startswith(("step ", "tradition "))):
        return f"{named.group(1)} {named.group(2)}"
    return base or label.strip()


_KEY_STOP = {"the", "a", "an", "this", "that", "our", "of", "to", "and", "&"}


def _stem(w: str) -> str:
    for suf, min_len in (("ing", 6), ("ies", 5), ("es", 6), ("s", 4), ("ed", 6)):
        if w.endswith(suf) and len(w) >= min_len and not w.endswith("ss"):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def merge_key(label: str) -> str:
    """Labels that differ only in articles, plurals, -ing or punctuation share a key
    ("Character Defects" = "Character Defect", "Carrying the Message" = "Carry This Message")."""
    words = [w for w in re.findall(r"[a-z0-9]+", label.lower().replace("’", "'")) if w not in _KEY_STOP]
    if words[:2] == ["a", "a"]:
        words = words[2:]
    return " ".join(_stem(w) for w in words)


def steps_and_traditions(lib: Library) -> dict[str, list[str]]:
    """The exact wording of the Twelve Steps and Traditions, read from the 12&12's opening pages
    (each is the n-th quoted paragraph of its section). Returns hub id → normalised texts."""
    out: dict[str, list[str]] = defaultdict(list)
    book = lib.book("twelve-steps-and-twelve-traditions")
    if book is None:
        return out
    for n, kind in ((0, "step"), (1, "tradition")):
        if n >= len(book.outline):
            continue
        a, z = book.spans[n]
        quoted = [b.text for b in book.blocks[a:z + 1]
                  if b.kind == "p" and b.text.startswith("“") and b.text.rstrip().endswith("”")][:12]
        for i, text in enumerate(quoted, 1):
            norm = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
            out[f"step_{i}" if kind == "step" else "traditions"].append(norm)
    return out


def wording_hub(key: str, label: str, wording: dict[str, list[str]]) -> str | None:
    """A long fragment of exactly one Step's or Tradition's wording belongs to that hub."""
    if len(label.split()) < 5 or len(key.split()) < 3:
        return None
    k = " ".join(re.findall(r"[a-z0-9]+", key.lower()))
    hits = [(hub, i) for hub, texts in wording.items() for i, t in enumerate(texts) if k in t]
    return hits[0][0] if len(hits) == 1 else None


# ── Stage 2b: dedupe ──────────────────────────────────────────────────────

DEDUPE_PROMPT = """These labels are nodes on a concept map of recovery literature. Find labels that name the SAME \
thing — the same person ("Bill W", "Bill Wilson", "William Wilson"), the same organization, place or book, or the \
same idea in different words ("Character Defects", "Defects of Character"). Do not group things that are merely \
related (Fear and Anxiety are different nodes). For each group of two or more, give the best display label as \
canonical and list every member. Also list labels that are not real names or ideas at all (commentary, broken \
fragments) under drop.

Labels:
{labels}"""


def dedupe(kept: list[dict]) -> list[dict]:
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ.get("LLM_API_KEY", ""), timeout=600)
    model = os.environ.get("LLM_MODEL", "dsv4")
    for k in kept:
        k["label"] = clean_label(k["label"])
    kept = [k for k in kept if k["label"] and merge_key(k["label"])]
    labels: dict[str, dict] = {}
    for k in kept:
        labels.setdefault(k["label"], {"type": k["type"], "hub": k["hub"], "count": 0})["count"] += k["count"]
    groups: dict[str, list[str]] = defaultdict(list)
    for lab, info in labels.items():
        bucket = info["type"] if info["type"] in ("person", "organization", "place", "text", "event") \
            else f"hub:{info['hub'] or 'none'}"
        groups[bucket].append(lab)
    jobs = []
    for bucket, labs in groups.items():
        labs.sort(key=str.lower)
        for i in range(0, len(labs), 220):
            if len(labs[i:i + 220]) > 1:
                jobs.append(labs[i:i + 220])
    schema = {"type": "object", "required": ["groups", "drop"], "properties": {
        "groups": {"type": "array", "items": {"type": "object", "required": ["canonical", "members"], "properties": {
            "canonical": {"type": "string"}, "members": {"type": "array", "items": {"type": "string"}}}}},
        "drop": {"type": "array", "items": {"type": "string"}}}}
    cache_path = os.path.join(WORK, "dedupe_batches.json")
    done: dict[str, dict] = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    def run(i: int) -> tuple[int, dict]:
        if str(i) in done:
            return i, done[str(i)]
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model, max_tokens=8000, temperature=0.1,
                    messages=[{"role": "user", "content": DEDUPE_PROMPT.format(labels="\n".join(jobs[i]))}],
                    extra_body={"structured_outputs": {"json": schema, "disable_any_whitespace": True},
                                "chat_template_kwargs": {"thinking": True, "reasoning_effort": "low"}, "priority": 5},
                )
                return i, json.loads(resp.choices[0].message.content)
            except Exception as exc:
                print(f"  dedupe {i} attempt {attempt + 1}: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(5)
        return i, {"groups": [], "drop": []}

    # Union-find over labels: groups that share a member (in any batch) merge,
    # so "Bill W"/"Bill Wilson" and "William Wilson"/"Mr. Wilson" become one.
    by_norm = {_norm_label(lab): lab for lab in labels}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    canon_votes: dict[str, Counter] = defaultdict(Counter)
    drop: set[str] = set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, out in pool.map(run, range(len(jobs))):
            done[str(i)] = out
            json.dump(done, open(cache_path, "w"))
            for g in out.get("groups", []):
                # The model sometimes writes non-breaking spaces into names.
                members = [by_norm[n] for n in (_norm_label(m) for m in g.get("members", [])) if n in by_norm]
                canon_raw = by_norm.get(_norm_label(g.get("canonical") or ""))
                if canon_raw:
                    members.append(canon_raw)
                members = list(dict.fromkeys(members))
                if len(members) < 2:
                    continue
                for m in members[1:]:
                    parent[find(m)] = find(members[0])
                canon = clean_label(g.get("canonical") or "")
                if sane_label(canon):
                    canon_votes[members[0]][canon] += 1
            drop |= {by_norm[n] for n in (_norm_label(d) for d in out.get("drop", [])) if n in by_norm}
            print(f"  dedupe {i + 1}/{len(jobs)}: {len(out.get('groups', []))} groups, {len(out.get('drop', []))} dropped",
                  flush=True)
    clusters: dict[str, list[str]] = defaultdict(list)
    for lab in labels:
        clusters[find(lab)].append(lab)
    rename: dict[str, str] = {}
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        votes: Counter = Counter()
        for m in members:
            votes.update(canon_votes.get(m, {}))
        best = votes.most_common(1)[0][0] if votes else None
        if not best or not sane_label(best):
            best = max(members, key=lambda m: (sane_label(m), labels[m]["count"]))
        for m in members:
            rename[m] = best
    out = []
    for k in kept:
        if (k["label"] in drop and k["label"] not in rename) or not sane_label(rename.get(k["label"], k["label"])):
            continue
        out.append(dict(k, label=rename.get(k["label"], k["label"])))
    out = merge_people(drop_stray_plurals(out))
    print(f"dedupe: {len(labels)} labels → {len({k['label'] for k in out})}", flush=True)
    return out


_TITLES = {"dr", "mr", "mrs", "ms", "rev", "jr", "sr", "st", "the", "s"}
_FIRST_NAMES = set("""paul james john david peter mark luke matthew thomas george henry charles william robert mary
anne ann ruth frank bill bob jim jack joe charlie carl lois clarence ebby hank marty""".split())


def _name_tokens(label: str) -> list[str]:
    words = re.findall(r"[a-z]+", label.lower().replace("’", "'").replace("'s", ""))
    return [w for w in words if w not in _TITLES]


def merge_people(items: list[dict]) -> list[dict]:
    """Fold short forms of a person's name into the one fuller name they point to
    ("Jung" → "Carl Jung", "Dr. Silkworth" → "Dr. William Silkworth", "Dr Bob's" → "Dr. Bob")."""
    people: dict[str, int] = Counter()
    for k in items:
        if k["type"] == "person":
            people[k["label"]] += k["count"]
    toks = {lab: _name_tokens(lab) for lab in people}
    rename: dict[str, str] = {}
    for lab, t in toks.items():
        if not t:
            continue
        same = [o for o, ot in toks.items() if o != lab and ot == t]
        if same:  # same name, different punctuation/possessive: keep the most used
            best = max([lab, *same], key=lambda x: people[x])
            if best != lab:
                rename[lab] = best
            continue
    # One surname, compatible first names (initials allowed) → one person:
    # "Jung" / "C.G. Jung" / "Carl Jung"; "Dr. Silkworth" / "William Duncan Silkworth".
    # A surname shared by different first names (Bob, Anne, Bernard Smith) is left alone.
    by_surname: dict[str, list[str]] = defaultdict(list)
    for lab, t in toks.items():
        if not t or len(t[-1]) < 4 or " and " in lab.lower() or lab in rename:
            continue
        if len(t) == 1 and t[0] in _FIRST_NAMES:
            continue  # "Paul" alone is more likely the apostle than Sheryl Paul
        by_surname[t[-1]].append(lab)
    for surname, group in by_surname.items():
        if len(group) < 2:
            continue
        firsts = {toks[g][0] for g in group if len(toks[g]) >= 2}
        if any(not (a.startswith(b) or b.startswith(a)) for a in firsts for b in firsts):
            continue
        best = max(group, key=lambda g: (len(toks[g]) >= 2, people[g]))
        for g in group:
            if g != best:
                rename[g] = best

    def resolve(lab: str) -> str:  # follow chains: "Dr. Jung" → "Jung" → "Carl Jung"
        seen = set()
        while lab in rename and lab not in seen:
            seen.add(lab)
            lab = rename[lab]
        return lab

    return [dict(k, label=resolve(k["label"])) if k["type"] == "person" else k for k in items]


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").replace("’", "'")).strip().lower()


_LOOP_WORDS = re.compile(r"\b(wait|hmm|actually|final answer|that's wrong|i think|keep true)\b", re.IGNORECASE)


def sane_label(label: str) -> bool:
    """Reject labels a model produced while looping or thinking aloud."""
    if not label or len(label) < 2 or len(label) > 60 or "?" in label or _LOOP_WORDS.search(label):
        return False
    words = re.findall(r"[A-Za-z']+", label.lower())
    if not words:
        return False
    if len(words) >= 5 and Counter(words).most_common(1)[0][1] >= 3:
        return False
    letters = sum(ch.isalpha() for ch in label)
    return letters / len(label) >= 0.6


def drop_stray_plurals(items: list[dict]) -> list[dict]:
    """"Bills", "Gods": possessive/plural fragments of names that exist as longer labels."""
    labels = {k["label"] for k in items}
    prefixes = {lab.split()[0] for lab in labels if " " in lab}
    out = []
    for k in items:
        lab = k["label"]
        if re.fullmatch(r"[A-Z][a-z]+s", lab) and lab[:-1] in prefixes and lab[:-1] not in labels:
            continue
        out.append(k)
    return out


# ── Stage 3: layout ───────────────────────────────────────────────────────


def build_layout(lib: Library, kept: list[dict]) -> dict:
    import numpy as np
    from scipy import sparse

    from src.rag.concept_text import ConceptMatcher

    # Merge synonyms by label; each concept keeps all its surface forms.
    hub_by_label = {label.lower(): tid for tid, label, *_ in TOPICS}
    # A concept that is one half of a theme's name is that theme ("Sobriety" →
    # "Sobriety & Clean Time", "Alcohol" → "Alcohol & Drinking").
    for tid, label, *_ in TOPICS:
        for part in re.split(r"\s*&\s*", label):
            if len(part) >= 4 and part.lower() not in hub_by_label:
                hub_by_label[part.lower()] = tid
                hub_by_label["the " + part.lower()] = tid
    tradition_hub = {"tradition " + w: "traditions" for w in
                     "one two three four five six seven eight nine ten eleven twelve".split()}
    extra_forms: dict[str, list[str]] = defaultdict(list)
    concepts: dict[str, dict] = {}
    canonical: dict[str, str] = {}
    wording = steps_and_traditions(lib)
    for k in kept:
        k = dict(k, label=clean_label(k["label"]))
        if not sane_label(k["label"]):
            continue
        merged = (hub_by_label.get(k["label"].lower()) or tradition_hub.get(k["label"].lower())
                  or wording_hub(k["key"], k["label"], wording))
        if merged:
            extra_forms[merged].append(k["key"])  # e.g. "remove our shortcomings" → Step Seven
            continue
        key = merge_key(k["label"])
        if not key:
            continue
        cid = canonical.setdefault(key, "c:" + re.sub(r"[^a-z0-9]+", "-", k["label"].lower()).strip("-"))
        c = concepts.setdefault(cid, {"id": cid, "label": k["label"], "type": k["type"], "hub": k["hub"],
                                      "forms": [], "kind": k["kind"], "votes": Counter()})
        c["votes"][k["label"]] += k["count"]
        c["forms"].append(k["key"])
        if not c["hub"] and k["hub"]:
            c["hub"] = k["hub"]
    for c in concepts.values():  # the most frequent spelling names the merged concept
        c["label"] = c.pop("votes").most_common(1)[0][0]
    hubs = {f"t:{tid}": {"id": f"t:{tid}", "label": label, "type": "topic", "hub": tid, "group": group,
                         "forms": [t.lower() for t in terms] + extra_forms.get(tid, []), "kind": "topic",
                         "extra_forms": extra_forms.get(tid, [])}
            for tid, label, group, _blurb, terms in TOPICS}
    nodes = list(hubs.values()) + sorted(concepts.values(), key=lambda c: c["id"])
    matcher = ConceptMatcher([(n["id"], n["forms"]) for n in nodes])
    rows, cols = [], []
    n_pass = 0
    for doc_id in lib.catalog():
        for p in passages_for_book(lib.book(doc_id)):
            hit = matcher.match(p.text)
            for nid in hit:
                rows.append(n_pass)
                cols.append(matcher.index[nid])
            n_pass += 1
    X = sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n_pass, len(nodes)))
    X.data[:] = 1.0
    df = np.asarray(X.sum(axis=0)).ravel()
    keep = df >= 5
    print(f"{int(keep.sum())}/{len(nodes)} nodes occur in ≥5 of {n_pass} passages", flush=True)
    idx = np.where(keep)[0]
    X = X[:, idx]
    nodes = [nodes[i] for i in idx]
    df = df[idx]
    C = (X.T @ X).tocoo()
    p_a = df / n_pass
    w_rows, w_cols, w_vals = [], [], []
    for a, b, n in zip(C.row, C.col, C.data):
        if a >= b or n < 3:
            continue
        p_ab = n / n_pass
        npmi = math.log(p_ab / (p_a[a] * p_a[b])) / -math.log(p_ab)
        if npmi > 0.05:
            w_rows += [a, b]
            w_cols += [b, a]
            w_vals += [npmi, npmi]
    W = sparse.csr_matrix((w_vals, (w_rows, w_cols)), shape=(len(nodes), len(nodes)))
    # Prominence: PageRank over the association graph, so ideas that bridge
    # many other ideas grow large (not merely frequent ones).
    deg = np.asarray(W.sum(axis=1)).ravel()
    deg[deg == 0] = 1
    P = sparse.diags(1 / deg) @ W
    r = np.full(len(nodes), 1 / len(nodes))
    for _ in range(60):
        r = 0.15 / len(nodes) + 0.85 * (P.T @ r)
    prominence = r / r.max()
    # Map position: embed each node by its association profile, then t-SNE.
    from sklearn.decomposition import TruncatedSVD
    from sklearn.manifold import TSNE
    feats = TruncatedSVD(n_components=min(48, len(nodes) - 1), random_state=7).fit_transform(W + sparse.eye(len(nodes)))
    feats /= np.linalg.norm(feats, axis=1, keepdims=True) + 1e-9
    xy = TSNE(n_components=2, perplexity=min(40, len(nodes) // 4), init="pca", random_state=7,
              metric="cosine").fit_transform(feats)
    xy -= xy.min(axis=0)
    xy /= xy.max(axis=0)
    group_of = {t[0]: t[2] for t in TOPICS}
    out_nodes = []
    for i, n in enumerate(nodes):
        out_nodes.append({
            "id": n["id"], "label": n["label"], "type": n["type"],
            "group": n.get("group") or group_of.get(n.get("hub") or "", "other"),
            "hub": n.get("hub"), "forms": n["forms"] if n["kind"] != "topic" else n.get("extra_forms", []),
            "x": round(float(xy[i, 0]), 4), "y": round(float(xy[i, 1]), 4),
            "prominence": round(float(prominence[i]), 4), "passages": int(df[i]),
        })
    return {"version": int(time.time()), "passages": n_pass,
            "groups": [{"id": g, "label": l} for g, l in GROUPS] + [{"id": "other", "label": "Other"}],
            "nodes": out_nodes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["mine", "curate", "dedupe", "layout"])
    ap.add_argument("--limit", type=int, default=9000, help="candidates sent to curation")
    args = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    lib = Library(DOCS)
    cand_path = os.path.join(WORK, "candidates.json")
    kept_path = os.path.join(WORK, "curated.json")
    if args.stage == "mine":
        json.dump(mine(lib), open(cand_path, "w"), indent=0)
        print("wrote", cand_path)
    elif args.stage == "curate":
        kept = curate(select_for_curation(json.load(open(cand_path)), args.limit))
        json.dump(kept, open(kept_path, "w"), indent=0)
        print(f"kept {len(kept)} → {kept_path}")
    elif args.stage == "dedupe":
        deduped = dedupe(json.load(open(kept_path)))
        json.dump(deduped, open(os.path.join(WORK, "deduped.json"), "w"), indent=0)
    else:
        src = os.path.join(WORK, "deduped.json")
        data = build_layout(lib, json.load(open(src if os.path.exists(src) else kept_path)))
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"wrote {OUT}: {len(data['nodes'])} nodes")


if __name__ == "__main__":
    main()
