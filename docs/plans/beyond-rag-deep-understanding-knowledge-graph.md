# Beyond RAG — Deep Understanding, Conceptual Citations & a Living Knowledge Graph

> **Status:** Design doc — no code written yet.
> **Owner:** Josh / Hermes
> **Repo:** `~/development/sobriety-copilot` (local-disk clone; ship via `deploy.sh`)

**Goal:** Move the app from *surface similarity over an undifferentiated chunk blob* to a *structured, concept-aware model of the literature* that (1) deeply understands the common topics, (2) answers nuanced questions and gives deep dives on any topic, (3) cites passages on **conceptual** (not lexical) relevance, and (4) renders that knowledge as a rich, dynamic, navigable graph.

**Core thesis:** All four goals fail today for the *same* reason — the corpus is treated as ~178k flat chunks scored by embedding/BM25 similarity, with a 12k-char context budget and a hand-authored ~20-node graph. The fix is architecture-wide: **build structured knowledge offline, retrieve against that structure, judge relevance with a model, and generate from long context.**

**Tech stack (current):** FastAPI (`src/server.py`), `src/rag/` (retriever, reranker, graph, embeddings), ChromaDB, Ollama (nomic-embed-text / all-minilm, EmbeddingGemma fine-tune), cross-encoder `ms-marco-MiniLM-L-6-v2` reranker, HyDE, RAGAS eval harness, Flutter mobile + PWA web (`static/` is a build artifact).

---

## Part 0 — The current architecture (what we're building on)

Verified from code:

| Piece | Where | What it does today |
|---|---|---|
| Embedding | `src/rag/embeddings.py` | Ollama `nomic-embed-text` (or all-minilm / EmbeddingGemma), `search_document:`/`search_query:` prefixes, 320-word/2000-char caps |
| Retrieval | `src/rag/retriever.py:528` | Hybrid semantic+BM25 → scale-bucket diversity → cross-encoder rerank → top-8 |
| Context budget | `retriever.py:59` `RAG_MAX_CONTEXT_CHARS=12000` | Caps injected literature (~one deep Step's worth max) |
| Enumeration penalty | `retriever.py:96` `.45×` | Demotes step-list chunks (FP for "all the steps" queries) |
| HyDE | `server.py:1090` | Rewrites query → hypothetical passage for embedding |
| Reranker | `src/rag/reranker.py` | `ms-marco-MiniLM-L-6-v2`, oversample 3×, sigmoid+boosts |
| Graph | `src/rag/graph.py` | Hand-authored `RECOVERY_TERMS` (~20) + `CORE_RECOVERY_NODES` (12) → static wheel |
| Manifests | `documents/.manifests/*.json` | **Already contain structure**: headings, block order, block_ids, printed pages |
| Eval | `tests/eval_rag.py` + `eval_cases.json` | RAGAS: faithfulness, answer_relevancy, context_precision, context_recall (3 cases today) |

**Key enabler already present:** the manifests record real document structure (verified: `twelve-steps-and-twelve-traditions.json` = 1024 blocks, 70 headings, per-Step 1k–21k words). The literature's *shape* exists — nothing reads it back out.

---

## Part 1 — Deep understanding & deep dives on any topic

### 1A. Long-context grounding (highest leverage, cheapest)

Problem: deep dives are stitched from 8 fragments ≤12k chars. Fix: for a "deep dive / whole-section / whole-book" query, **load the entire relevant section (or book) into the model's context** — don't fragment. Verified Step sections are 1k–3.5k words (Step Twelve ~21k); the whole 12&12 chapter per step fits. A 128k-context local model (your 128GB Mac can run one) holds a whole book.

`/api/deepdive?topic=X&doc=<doc_id>&section=<section>` → assemble the section's full text from the manifest → single long-context generation → whole-source reasoning instead of 8-fragment stitching.

### 1B. Structured topic extraction + community detection (GraphRAG-style, offline)

Instead of ~20 hand-typed `RECOVERY_TERMS`, run an offline LLM pass over the corpus to extract **entities, concepts, and typed relationships** (e.g. `serenity ↔ surrender`, `Step 4 → inventory → resentment`), then run **community detection** (Leiden/Louvain) to organize into a **hierarchy**: coarse motifs → communities → sub-concepts → passages. Each community gets a pre-computed **summary + key quote**.

This is what delivers "the most common topics deeply understood": the dominant themes get pre-distilled into structured, citing communities rather than being re-derived per query.

### 1C. Domain fine-tune for genuine subject-matter understanding

You already have the SFT pipeline (EmbeddingGemma, gated SFT generator). Add/reuse a **domain fine-tune (SFT + preference/DPO)** on the recovery corpus so the **weights** absorb the framing, vocabulary, and theology — enabling nuanced synthesis and cross-chapter connections that retrieval alone can't make.

**Division of labor (critical):**
- **Grounding/retrieval layer = authoritative sources** (citations must come from here — a fine-tuned model will confidently *invent* attributions otherwise).
- **Reasoning layer (long-context + fine-tuned) = nuance, synthesis, explanation.**

Keep RAG authoritative for sourcing; move the *thinking* into a better model + longer context.

---

## Part 2 — Conceptual citations (not word-matching)

This is the most tractable and highest-value change. Today: query → embedding+BM25+HyDE → passages ranked by **surface similarity**. A "serenity" query never surfaces "acceptance is the answer" because the words differ. Fix with **two conceptual layers** on top of the broadened candidate pool:

**Layer 1 — LLM concept expansion (upgrade HyDE).** Before retrieval, the model rewrites the query into **conceptual facets incl. related-but-unstated concepts**:
```
"serenity" → {serenity, peace, acceptance, presence, letting go of control,
              the Serenity Prayer, surrender, not being upset by people/places/things}
```
Run one embedding query **per facet**, fuse results. This pulls in the passages that *apply* without sharing the query's words. Extends existing `_referenced_source_substrings` / `RECOVERY_TERMS` machinery from ~20 terms to model-generated facets.

**Layer 2 — LLM relevance labeling + concept tags.** After the cross-encoder's coarse shortlist, run an **LLM-as-judge pass** over the top ~30 candidates: *"Does this passage actually address the user's underlying concern, even if it never uses their words? Which concepts does it speak to?"* Attach the **concept tag** to the citation chip. So a chip stops reading just `Relevance 78%` and reads e.g. `Acceptance · touches Step 11`.

Combined effect on citations:
- Passage kept as evidence; **concept tag** surfaced on the chip.
- `ENUMERATION_PENALTY` no longer needed on the answer path for broad questions — you're grounding in concept-mapped sections, not fighting TOC pages.

> **Honest caveat:** "does this passage conceptually apply?" is fundamentally an **LLM judgment** — embeddings can't fully do it. That's *why* the model sits on top of a broadened candidate pool rather than expecting the vector store to solve it alone.

---

## Part 3 — Evaluation: proving "deep understanding" (make it measurable)

Extend the existing RAGAS harness (`tests/eval_rag.py`) into a **Grounded-on-Text eval set**:

- Per common topic: questions + ideal answers + the **support passages** — and deliberately include support passages that **don't contain the query's words**, to force conceptual (not lexical) retrieval.
- Metrics, per answer:
  - **Faithfulness / source-groundedness** — every claim attributable to a retrieved passage (guards the fine-tuned-model-invention risk).
  - **Concept coverage** — did retrieval surface the non-obvious-but-on-topic passages? (the "failure/serenity" test).
  - **Answer relevancy / quality** — LLM-judge vs ideal answer.
- Gate: retrieval/concept-expansion/fine-tune changes must not regress the suite. Add specific **conceptual-citation test cases** so "help me expand X" can't silently break citation quality.

---

## Part 4 — A rich, living knowledge graph

Current graph is a **static hand-authored ~20-node wheel** (`graph.py`): query → 6 passages + 12 steps + 3 prompts; taps refetch but there's no deeper hierarchy.

### 4A. Feed it the structured ontology (§1B)

The community/concept hierarchy **is** the graph data. Navigation becomes: query → top-level motifs → drill into communities → sub-concepts → specific passages. This yields **"an order of magnitude more topics as you navigate"** because each level is real extracted structure, not a hand-typed list — and every node becomes an entry point.

### 4B. Physics-based, animated, semantic-zoom rendering

Replace the static layout with a **force-directed / WebGL graph**:
- **Web PWA:** `three.js` / `force-graph`-style WebGL canvas.
- **Flutter:** `graphview`, CustomPainter, or an embedded WebGL canvas (reuse `rag_graph_view.dart`).

Features that directly answer each complaint:
- **Physics animation** — nodes repel/attract, edges spring, structure settles adaptively (the "dynamic and animated" ask).
- **Click-to-expand neighbors** — every node expands its connected concepts/passages on click (the "not all topics are clickable" ask → all nodes clickable).
- **Semantic zoom / concept clusters** — zoomed-out = topic communities; zoom-in = passages; the graph **re-anchors around the focused concept** (extends the earlier step-specific graph focus fix to a rich hierarchy).
- **Inline deep dive from the node** — tapping a cluster opens the grounded deep dive from §1, tying the visualization back into real understanding (not just a label).

---

## The unifying architecture

```
             corpus (manifests + 178k chunks)
                       │
        ┌──────────────┴──────────────┐
        │   OFFLINE (once per build)   │
        │  - LLM entity/concept         │
        │    extraction                 │
        │  - community detection        │ ──► structured ontology /
        │  - per-topic summaries         │     concept graph + long-form text
        └──────────────┬──────────────┘
                       │
        ┌──────────────┴──────────────┐
        │   QUERY TIME                 │
  L1     LLM concept expansion         │  query "failure" → facets
  L2     retrieval (embedding facets   │
          + BM25) over candidate pool │
  L3     LLM relevance filter +        │ ──► citations w/ concept tags
          concept labeling             │
  L4     LLM generate, grounded in     │ ──► deep dive (long-context)
          section-level context        │
        └──────────────┴──────────────┘
                       │
         frontends: deep-dive + dynamic graph (WebGL)
```

---

## Implementation order (fast value first)

1. **Conceptual citations (backend only, highest payoff, no new UI):** LLM concept expansion (Layer 1) + LLM relevance/tag pass (Layer 2). Add `tests/eval_cases.json` conceptual cases; gate on the harness.
2. **Long-context deep dives (backend + modest surface):** `/api/deepdive` via manifests; wire a deep-dive entry into chat.
3. **Structured ontology + communities (offline build):** feeds both the graph and the deep dives.
4. **Domain fine-tune + eval expansion:** deeper reasoning; keep retrieval authoritative for sourcing.
5. **WebGL graph remake (most visible, last):** force-directed, animated, semantic zoom, click-to-expand, inline deep dive. Flutter + PWA; rebuild `static/` + `deploy.sh`.

Each step is independently shippable and de-risks the next.

---

## Anti-goals / guardrails

- **No server-side human moderation, no multi-user** — stays on-device/single-user (per FR triage stance, `feature-requests.md:36`).
- **Privacy preserved** — all reading is local/corpus; nothing new leaves the existing privacy boundary.
- **Literature-grounded, not invented** — anchored summaries/quotes come from curated passages; generation is grounded in retrieved sources; eval *forces* faithfulness.
- **Don't regress precision** — the normal single-shot retrieval path stays intact for specific factual questions; the new layers are additive.

---

## Open questions to settle before coding

1. **Fine-tune vs. long-context-first:** how much weight on 1C (domain fine-tune, expensive, needs GPU/data) vs. 1A+1B (long-context + structured indexing, cheaper, fast payoff)? Recommend 1A+1B first; 1C opportunistically.
2. **Local model for the conceptual layers:** the LLM judges/facet-expansion run on Ollama locally (latency, privacy) — is the 31B-tier model fast enough, or do we run these offline in a batch for the ontology and use a lighter model at query time?
3. **Where deep-dive + graph surface:** extend the existing graph screen, a new "Study" menu entry, or inline in chat? (Recommend: graph screen becomes the "study" surface + a chat starter suggestion.)
4. **Ontology scope:** v1 = 12&12 Steps + Big Book common topics only, or all four document categories? (Recommend: 12&12 + Big Book first; loader generic.)
5. **Which graph lib:** native Flutter (`graphview`/CustomPainter) vs. embedded WebGL canvas — the latter gives richer animation + one code path for both web and mobile. Recommend embedded WebGL.
