#!/usr/bin/env python3
"""Build the dynamic 92-topic / 1,800+ prompt catalog for the mobile & web app.

Sources:
1. Hand-curated starter prompts in `mobile_app/lib/data/starter_prompts.dart`
   and `mobile_app/lib/features/daily/study_themes.dart`
2. 92 canonical recovery topics in `src/rag/graph_taxonomy.py`
3. 2,557 literature sub-concepts & NPMI layout in `src/rag/data/graph_concepts.json`
4. Vetted user recovery questions from `finetune/gen/taxonomy.json` and
   `finetune/gen/sft.filtered.jsonl`

Outputs:
  `mobile_app/lib/data/topic_prompts_catalog.dart`
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rag.graph_taxonomy import TOPICS  # noqa: E402

CONCEPTS_PATH = ROOT / "src/rag/data/graph_concepts.json"
TAX_JSON_PATH = ROOT / "finetune/gen/taxonomy.json"
SFT_JSONL_PATH = ROOT / "finetune/gen/sft.filtered.jsonl"
STARTER_DART_PATH = ROOT / "mobile_app/lib/data/starter_prompts.dart"
STUDY_THEMES_PATH = ROOT / "mobile_app/lib/features/daily/study_themes.dart"
OUTPUT_DART_PATH = ROOT / "mobile_app/lib/data/topic_prompts_catalog.dart"

# Reject second-person coaching voice, dangling passage references, and narrow
# reading-comprehension story trivia.
REJECT_RE = re.compile(
    r"\b("
    r"you|your|yours|yourself|"
    r"this passage|this chapter|this section|this story|this reading|this text|this book|"
    r"the passage|the excerpt|the speaker|the narrator|the author|the writer|"
    r"according to the passage|in the passage|in the text above|part two|part one|"
    r"page \d+|pages \d+|chapter \d+ says|"
    r"the lady|the soldier|the man|the woman|the boy|the girl|the doctor in the story|"
    r"helicopter|admiral|lawyer|cissy|bobby|me-ma|thistle|dalai lama"
    r")\b",
    re.IGNORECASE,
)

# Require an unmistakable recovery / spiritual / first-person anchor for SFT questions
RECOVERY_ANCHOR_RE = re.compile(
    r"\b("
    r"i |i'm|i’m|i've|my |me |we |our |"
    r"recovery|sober|sobriety|step|steps|tradition|traditions|sponsor|sponsee|"
    r"big book|twelve and twelve|12 and 12|a\.a\.|aa|alcoholics anonymous|fellowship|"
    r"program|literature|higher power|god|amends|inventory|resentment|resentments|"
    r"craving|cravings|relapse|prayer|meditation|humility|gratitude|acceptance|"
    r"surrender|forgive|forgiveness|fear|anger|shame|guilt|meeting|meetings|"
    r"home group|newcomer|drinking|drunk|alcoholic|addiction|clean|spiritual|"
    r"serenity|powerless|powerlessness|unmanageable|character defect|shortcoming|"
    r"service|anonymity|emotional sobriety|halt|bill w|dr\.? bob|daily reflection|"
    r"promises|we agnostics|fourth step|fifth step|ninth step|tenth step|eleventh step"
    r")\b",
    re.IGNORECASE,
)

VALID_IMPERATIVE_START_RE = re.compile(
    r"^("
    r"Help me|Walk me through|Show me|Tell me|Explain|Share|Read me|Give me|"
    r"Talk me through|Remind me|I |I'm |I’ve |I've |My |Tonight |The house "
    r")",
    re.IGNORECASE,
)

QUESTION_START_RE = re.compile(
    r"^("
    r"What|How|Why|When|Where|Who|Which|Can|Could|Should|Does|Do|Is|Are|Will|Would|Did"
    r")\b",
    re.IGNORECASE,
)

MORNING_TOPICS = {
    "step_11", "prayer", "meditation", "gratitude", "acceptance", "willingness",
    "surrender", "step_3", "higher_power", "serenity", "awakening",
    "one_day", "present", "humility", "faith", "open_mindedness",
}
EVENING_TOPICS = {
    "step_10", "resentment", "amends", "step_8", "step_9", "forgiveness",
    "guilt", "shame", "honesty", "anger", "self_pity", "family", "partners",
    "relationships", "emotional_sobriety", "ego", "selfishness", "inventory",
    "writing",
}
LATE_TOPICS = {
    "craving", "relapse", "powerlessness", "step_1", "fear",
    "isolation", "grief", "depression", "anxiety", "bottom", "hope",
    "self_care", "withdrawal", "stress",
}


def topic_time_affinity(topic_id: str) -> str:
    if topic_id in MORNING_TOPICS:
        return "morning"
    if topic_id in EVENING_TOPICS:
        return "evening"
    if topic_id in LATE_TOPICS:
        return "late"
    return "day"


def term_to_regex(term: str) -> str:
    words = term.strip().lower().split()
    parts: list[str] = []
    for w in words:
        if w.endswith("*"):
            stem = re.escape(w[:-1])
            parts.append(rf"{stem}\w*")
        else:
            parts.append(re.escape(w))
    return r"\b" + r"[\s\-]+".join(parts) + r"\b"


def clean_prompt(raw: str, *, trusted: bool = False) -> str | None:
    s = " ".join(raw.strip().split())
    if not s:
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    if len(s) < 22 or len(s) > 118:
        return None
    if not trusted:
        if REJECT_RE.search(s):
            return None
        if not RECOVERY_ANCHOR_RE.search(s):
            return None
        is_q = s.endswith("?") and bool(QUESTION_START_RE.match(s))
        is_imp = (s.endswith(".") or s.endswith("?")) and bool(VALID_IMPERATIVE_START_RE.match(s))
        if not (is_q or is_imp):
            return None
        if re.search(r"\b(what year did|how many copies|which edition|isbn|copyright)\b", s, re.I):
            return None
    s = s[0].upper() + s[1:]
    return s


TYPE_TEMPLATES: dict[str, list[str]] = {
    "saying": [
        "What does the recovery saying '{raw}' mean in daily practice?",
        "Where does '{raw}' come from in the literature, and how do I apply it?",
        "How can '{raw}' help me stay grounded today?",
        "Explain the deeper lesson behind '{raw}' in recovery.",
    ],
    "prayer": [
        "How do people in recovery use '{raw}' in their daily practice?",
        "Share the meaning and spirit behind '{raw}'.",
        "How can I bring '{raw}' into my step eleven quiet time?",
    ],
    "practice": [
        "What does the literature teach about '{raw}' in recovery?",
        "How do I build '{raw}' into my daily recovery routine?",
        "Walk me through how '{raw}' supports {topic}.",
        "Show me a passage about '{raw}' and how to practice it one day at a time.",
    ],
    "emotion": [
        "How does the program suggest handling '{raw}' without picking up a drink?",
        "What does the Big Book say when '{raw}' shows up in recovery?",
        "Help me work through '{raw}' using the tools of {topic}.",
        "Show me a passage that speaks to '{raw}' in sobriety.",
    ],
    "trait": [
        "What does the Twelve and Twelve teach about '{raw}'?",
        "How does '{raw}' affect my recovery and relationships?",
        "Help me look honestly at '{raw}' in my personal inventory.",
    ],
    "condition": [
        "What does the recovery literature say about '{raw}'?",
        "How do people in the fellowship navigate '{raw}' one day at a time?",
        "Help me understand how '{raw}' relates to {topic}.",
    ],
    "text": [
        "What are the core recovery lessons in '{raw}'?",
        "What should I look for when reading '{raw}' with my sponsor?",
        "Share the main takeaway from '{raw}' for daily sobriety.",
    ],
    "concept": [
        "What does the literature mean by '{raw}', and how does it apply to {topic}?",
        "How does the Big Book explain '{raw}' in daily recovery?",
        "Help me reflect on '{raw}' and what it means for my sobriety today.",
        "Show me a passage about '{raw}' and how to apply it one day at a time.",
        "How can I talk with my sponsor about '{raw}' when working on {topic}?",
    ],
}

ALLOWED_CONCEPT_TYPES = set(TYPE_TEMPLATES.keys())

SKIP_SINGLE_WORDS = {
    "believe", "sane", "insane", "working", "came", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "first",
    "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "steps", "step", "piece",
    "normal", "abnormal", "active", "able", "unable", "willing", "unwilling",
    "ready", "open", "closed", "good", "bad", "right", "wrong",
}


def synthesize_subconcept_prompts(
    topic_id: str,
    topic_label: str,
    subconcepts: list[dict],
) -> list[str]:
    """Generate clean, literature-grounded questions tailored to each sub-concept's type."""
    out: list[str] = []
    for idx, sc in enumerate(subconcepts):
        ctype = sc.get("type", "concept")
        if ctype not in ALLOWED_CONCEPT_TYPES:
            continue
        raw_lbl = sc.get("label", "").strip()
        lbl = raw_lbl.lower()
        if len(lbl) < 5 or len(lbl) > 40 or lbl == topic_label.lower():
            continue
        if lbl in SKIP_SINGLE_WORDS:
            continue
        if any(ch in raw_lbl for ch in ("(", ")", "/", ":", "'", '"', "—")):
            continue
        if REJECT_RE.search(raw_lbl):
            continue
        templates = TYPE_TEMPLATES.get(ctype, TYPE_TEMPLATES["concept"])
        tmpl = templates[idx % len(templates)]
        q = tmpl.format(concept=lbl, raw=raw_lbl, topic=topic_label)
        cleaned = clean_prompt(q, trusted=True)
        if cleaned:
            out.append(cleaned)
    return out


def main() -> None:
    concepts_data = json.loads(CONCEPTS_PATH.read_text())

    # 1. Map subconcepts and NPMI peer topics per canonical topic id
    subconcepts_by_topic: dict[str, list[dict]] = defaultdict(list)
    topic_coords: dict[str, tuple[float, float, str]] = {}
    for node in concepts_data.get("nodes", []):
        hub = node.get("hub")
        if not hub:
            continue
        if node.get("type") == "topic":
            topic_coords[hub] = (
                float(node.get("x", 0.5)),
                float(node.get("y", 0.5)),
                str(node.get("group", "")),
            )
            subconcepts_by_topic[hub].append(node)
        else:
            subconcepts_by_topic[hub].append(node)

    for tid in subconcepts_by_topic:
        subconcepts_by_topic[tid].sort(
            key=lambda c: (0 if c.get("type") == "topic" else 1, -int(c.get("passages", 0)))
        )

    peer_topics: dict[str, list[str]] = {}
    for tid, _label, group, _blurb, _terms in TOPICS:
        x1, y1, _ = topic_coords.get(tid, (0.5, 0.5, group))
        dists: list[tuple[float, str]] = []
        for other_tid, _ol, other_group, _ob, _ot in TOPICS:
            if other_tid == tid:
                continue
            x2, y2, _ = topic_coords.get(other_tid, (0.5, 0.5, other_group))
            dist = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            if other_group == group:
                dist *= 0.85
            dists.append((dist, other_tid))
        dists.sort()
        peer_topics[tid] = [other for _, other in dists[:6]]

    # 2. Build keyword matchers for all 92 topics (including subconcept forms)
    topic_keywords: dict[str, list[str]] = {}
    compiled_topic_res: list[tuple[str, re.Pattern]] = []
    for tid, _label, _group, _blurb, terms in TOPICS:
        kws: list[str] = []
        seen_kw: set[str] = set()
        for term in terms:
            clean_kw = term.replace("*", "").strip().lower()
            if len(clean_kw) >= 3 and clean_kw not in seen_kw:
                seen_kw.add(clean_kw)
                kws.append(clean_kw)
        for sc in subconcepts_by_topic.get(tid, [])[:30]:
            for form in [sc.get("label", ""), *sc.get("forms", [])]:
                f_clean = form.strip().lower()
                if 3 <= len(f_clean) <= 32 and f_clean not in seen_kw:
                    seen_kw.add(f_clean)
                    kws.append(f_clean)
        topic_keywords[tid] = kws[:45]
        raw_union = "|".join(f"(?:{term_to_regex(term)})" for term in terms)
        compiled_topic_res.append((tid, re.compile(raw_union, re.IGNORECASE)))

    def match_topics_for_text(text: str) -> list[str]:
        matched: list[str] = []
        for tid, rx in compiled_topic_res:
            if rx.search(text):
                matched.append(tid)
        if not matched:
            low = text.lower()
            for tid, kws in topic_keywords.items():
                if any(kw in low for kw in kws[:15]):
                    matched.append(tid)
        return matched

    # 3. Collect candidate prompts per topic
    prompts_by_topic: dict[str, list[str]] = defaultdict(list)
    global_seen: set[str] = set()

    def add_prompt(tid: str, raw: str, *, trusted: bool = False) -> bool:
        cleaned = clean_prompt(raw, trusted=trusted)
        if not cleaned:
            return False
        key = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
        if key in global_seen:
            return False
        global_seen.add(key)
        prompts_by_topic[tid].append(cleaned)
        return True

    # 3a. Existing hand-curated starter_prompts.dart & study_themes.dart (trusted)
    for path in (STARTER_DART_PATH, STUDY_THEMES_PATH):
        if not path.exists():
            continue
        src = path.read_text()
        for m in re.finditer(r'^\s*["\']([^"\'\n]{22,130})["\'],\s*$', src, re.M):
            q = m.group(1)
            tids = match_topics_for_text(q)
            target_tid = tids[0] if tids else "one_day"
            add_prompt(target_tid, q, trusted=True)

    # 3b. Finetune taxonomy.json questions
    if TAX_JSON_PATH.exists():
        tax_data = json.loads(TAX_JSON_PATH.read_text())
        rows = tax_data if isinstance(tax_data, list) else tax_data.get("items", [])
        for row in rows:
            if isinstance(row, dict):
                if row.get("category") in ("off_topic", "crisis"):
                    continue
                q = row.get("question", "")
            else:
                q = str(row)
            tids = match_topics_for_text(q)
            for tid in tids[:2]:
                if len(prompts_by_topic[tid]) < 16:
                    if add_prompt(tid, q, trusted=False):
                        break

    # 3c. Finetune SFT filtered questions
    if SFT_JSONL_PATH.exists():
        with SFT_JSONL_PATH.open() as f:
            for line in f:
                row = json.loads(line)
                if row.get("category") in ("off_topic", "crisis"):
                    continue
                q = row.get("question", "")
                tids = match_topics_for_text(q)
                for tid in tids[:2]:
                    if len(prompts_by_topic[tid]) < 16:
                        if add_prompt(tid, q, trusted=False):
                            break

    # 3d. Enrich every topic with sub-concept-driven prompts from graph_concepts.json
    for tid, label, _group, blurb, _terms in TOPICS:
        synth = synthesize_subconcept_prompts(
            tid, label, subconcepts_by_topic.get(tid, [])
        )
        for q in synth:
            if len(prompts_by_topic[tid]) >= 22:
                break
            add_prompt(tid, q, trusted=True)

        if len(prompts_by_topic[tid]) < 16:
            fallbacks = [
                f"What does the recovery literature teach about {label}?",
                f"How does the Big Book explain {label}?",
                f"What does the Twelve and Twelve say about {label}?",
                f"Show me key passages on {label} from the literature.",
                f"How do people in recovery practice {label} day to day?",
                f"Help me study {label} — {blurb.lower()}.",
                f"What are the most important lessons about {label} in A.A.?",
                f"How can I talk with my sponsor about {label}?",
                f"Share a daily reflection or reading centered on {label}.",
                f"What common misunderstandings exist around {label} in recovery?",
                f"How does {label} connect to spiritual growth in the program?",
                f"Walk me through how early members approached {label}.",
            ]
            for q in fallbacks:
                if len(prompts_by_topic[tid]) >= 18:
                    break
                add_prompt(tid, q, trusted=True)

    total_prompts = sum(len(v) for v in prompts_by_topic.values())
    total_subconcepts = sum(len(v) for v in subconcepts_by_topic.values())
    print(
        f"Generated {total_prompts} vetted prompts across {len(TOPICS)} topics "
        f"(indexing {total_subconcepts} sub-concepts)."
    )

    # 4. Emit Dart file
    lines = [
        "// GENERATED CODE - DO NOT EDIT BY HAND.",
        "// Generated by scripts/build_starter_catalog.py from:",
        "//   - src/rag/graph_taxonomy.py (92 canonical recovery topics)",
        "//   - src/rag/data/graph_concepts.json (2,557 literature sub-concepts & NPMI layout)",
        "//   - finetune/gen/taxonomy.json & sft.filtered.jsonl",
        "library;",
        "",
        "/// Metadata, sub-concept keywords, peer graph edges, and curated prompts",
        "/// for a single recovery topic in the 92-topic taxonomy.",
        "class RecoveryTopicEntry {",
        "  final String id;",
        "  final String label;",
        "  final String group;",
        "  final String blurb;",
        "  final String timeAffinity; // 'morning' | 'day' | 'evening' | 'late'",
        "  final List<String> keywords;",
        "  final List<String> peerTopicIds;",
        "  final List<String> prompts;",
        "",
        "  const RecoveryTopicEntry({",
        "    required this.id,",
        "    required this.label,",
        "    required this.group,",
        "    required this.blurb,",
        "    required this.timeAffinity,",
        "    required this.keywords,",
        "    required this.peerTopicIds,",
        "    required this.prompts,",
        "  });",
        "}",
        "",
        f"/// Full 92-topic recovery catalog ({total_prompts} vetted starter prompts).",
        "const List<RecoveryTopicEntry> kRecoveryTopicCatalog = [",
    ]

    def dart_str(s: str) -> str:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
        return f'"{escaped}"'

    for tid, label, group, blurb, _terms in TOPICS:
        affinity = topic_time_affinity(tid)
        kws = topic_keywords[tid]
        peers = peer_topics[tid]
        ps = prompts_by_topic[tid]

        lines.append("  RecoveryTopicEntry(")
        lines.append(f"    id: {dart_str(tid)},")
        lines.append(f"    label: {dart_str(label)},")
        lines.append(f"    group: {dart_str(group)},")
        lines.append(f"    blurb: {dart_str(blurb)},")
        lines.append(f"    timeAffinity: {dart_str(affinity)},")
        lines.append(f"    keywords: [{', '.join(dart_str(k) for k in kws)}],")
        lines.append(f"    peerTopicIds: [{', '.join(dart_str(p) for p in peers)}],")
        lines.append("    prompts: [")
        for p in ps:
            lines.append(f"      {dart_str(p)},")
        lines.append("    ],")
        lines.append("  ),")

    lines.append("];")
    lines.append("")

    OUTPUT_DART_PATH.write_text("\n".join(lines))
    print(f"Wrote {OUTPUT_DART_PATH} ({OUTPUT_DART_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
