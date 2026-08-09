"""RAG Knowledge Graph generator for literature passages, steps, and prompt nodes."""

from __future__ import annotations

from typing import Any
import os
import re

from src.rag.retriever import RAGRetriever


CORE_RECOVERY_NODES = [
    {"id": "step_1", "label": "Step 1: Powerlessness & Honesty", "type": "step", "category": "surrender"},
    {"id": "step_2", "label": "Step 2: Hope & Higher Power", "type": "step", "category": "hope"},
    {"id": "step_3", "label": "Step 3: Surrender & Trust", "type": "step", "category": "surrender"},
    {"id": "step_4", "label": "Step 4: Fourth-Step Inventory", "type": "step", "category": "inventory"},
    {"id": "step_5", "label": "Step 5: Confession & Integrity", "type": "step", "category": "inventory"},
    {"id": "step_6", "label": "Step 6: Willingness to Change", "type": "step", "category": "defects"},
    {"id": "step_7", "label": "Step 7: Humility & Seventh Step Prayer", "type": "step", "category": "defects"},
    {"id": "step_8", "label": "Step 8: List of Amends", "type": "step", "category": "amends"},
    {"id": "step_9", "label": "Step 9: Direct Restitution & Amends", "type": "step", "category": "amends"},
    {"id": "step_10", "label": "Step 10: Daily Spot-Check Inventory", "type": "step", "category": "maintenance"},
    {"id": "step_11", "label": "Step 11: Prayer & Morning Meditation", "type": "step", "category": "maintenance"},
    {"id": "step_12", "label": "Step 12: Service & Spiritual Awakening", "type": "step", "category": "service"},
]


RECOVERY_TERMS = [
    "willingness", "amends", "resentment", "surrender", "rigorous honesty",
    "higher power", "inventory", "acceptance", "fellowship", "sponsorship",
    "serenity", "fear", "defects of character", "spiritual awakening", "prayer",
    "meditation", "daily reflections", "big book", "twelve steps", "restitution"
]


def _slugify(value: str) -> str:
    """Normalise a term/label into a URL-safe, whitespace-free id fragment."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _enrich_from_ontology(
    ontology: dict[str, Any],
    q: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_ids: set[str],
    central_id: str,
    max_neighbors: int = 6,
    max_passages: int = 4,
) -> None:
    """Add concept + passage nodes from the ontology's co-occurrence graph.

    Purely additive: given the query, find concepts in the ontology that match
    the query, then pull in their co-occuring neighbour concepts (weighted by
    how often they appear together in the same literature section) plus the
    documents those concepts are grounded in. Everything is namespaced under an
    ``onto_`` id prefix so it can never collide with (or break) the hand-authored
    step/term/passage nodes.
    """
    q_lower = (q or "").lower()
    terms = ontology.get("concepts", [])
    edges_list = ontology.get("edges", [])
    doc_coverage = ontology.get("doc_coverage", {}) or {}

    # index of docs by id -> display title (best-effort label for passage nodes)
    doc_titles = {
        (d.get("doc_id") or str(id(d))): d.get("title") or d.get("category") or "Recovery Literature"
        for d in ontology.get("docs", [])
    }

    # term -> row lookup
    term_rows: dict[str, dict[str, Any]] = {}
    for row in terms:
        t = row.get("term")
        if t:
            term_rows[t] = row

    # adjacency: concept -> [(neighbour, weight), ...] (undirected, sorted by weight desc)
    adjacency: dict[str, list[tuple[str, int]]] = {}
    for e in edges_list:
        src, tgt, w = e.get("source"), e.get("target"), int(e.get("weight", 1))
        if src and tgt and src != tgt:
            adjacency.setdefault(src, []).append((tgt, w))
            adjacency.setdefault(tgt, []).append((src, w))
    for nb in adjacency.values():
        nb.sort(key=lambda item: (-item[1], item[0]))

    # Which concepts match the query? A concept matches if its term appears as a
    # phrase in the query, or is a single token of the query.
    q_tokens = set(re.findall(r"[a-z']+", q_lower))
    matched: list[str] = []
    for term, row in term_rows.items():
        tl = term.lower()
        term_words = tl.split()
        in_query = tl in q_lower
        # phrase concepts are matched as an exact substring; single words as a token
        if len(term_words) > 1:
            concept_hit = in_query
        else:
            concept_hit = term in q_tokens
        if concept_hit:
            matched.append(term)

    if not matched:
        return

    # Gather neighbour concepts (deduped, ordered by highest weight across matches)
    neighbour_rank: dict[str, int] = {}
    for term in matched:
        for nb, w in adjacency.get(term, []):
            if nb not in term_rows:
                continue
            # keep the best (largest) weight seen for each neighbour
            if nb not in neighbour_rank or w > neighbour_rank[nb]:
                neighbour_rank[nb] = w
    selected = sorted(neighbour_rank.items(), key=lambda item: (-item[1], item[0]))[:max_neighbors]

    new_concepts: list[str] = []
    for concept, _w in selected:
        c_id = f"onto_c_{_slugify(concept)}"
        if c_id in node_ids:
            continue
        nodes.append({
            "id": c_id,
            "label": concept.title(),
            "type": "concept",
            "category": "ontology",
            "term": concept,
        })
        node_ids.add(c_id)
        new_concepts.append(concept)
        edges.append({"source": central_id, "target": c_id, "label": "relates to"})

    # Ground each added concept in the docs it appears in (data-driven passages).
    for concept in new_concepts:
        for doc_id in (doc_coverage.get(concept) or [])[:max_passages]:
            p_id = f"onto_p_{_slugify(doc_id)}_{_slugify(concept)}"
            if p_id in node_ids:
                continue
            nodes.append({
                "id": p_id,
                "label": f"{concept.title()} — {doc_titles.get(doc_id, doc_id)}",
                "type": "passage",
                "source": doc_titles.get(doc_id, doc_id),
                "category": "ontology",
            })
            node_ids.add(p_id)
            edges.append({"source": f"onto_c_{_slugify(concept)}", "target": p_id, "label": "appears in"})


def build_knowledge_graph(
    query: str,
    retriever: RAGRetriever | None = None,
    ontology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a node-and-edge graph payload centered around `query` with cross-connected terms and literature sources.

    ``ontology`` is optional and additive. When provided (a dict as produced by
    :func:`src.rag.ontology.build_ontology`), the graph is enriched with extra
    ``concept`` nodes drawn from the ontology's co-occurrence edges — the
    neighbours of concepts that match the query — plus data-driven ``passage``
    nodes grounding those concepts in the documents where they appear. When
    ``ontology`` is ``None`` (the default), the graph is built exactly as before,
    preserving the hand-authored behavior.
    """
    q = (query or "The Twelve Steps").strip()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    central_id = f"term_{q.lower().replace(' ', '_')}"
    nodes.append({
        "id": central_id,
        "label": q,
        "type": "query",
        "category": "central",
    })
    node_ids.add(central_id)

    results = retriever.retrieve(q, top_k=6) if retriever else []

    for idx, res in enumerate(results):
        source_clean = os.path.splitext(os.path.basename(res.source))[0].replace("_", " ")
        if " - " in source_clean:
            source_clean = source_clean.split(" - ", 1)[0]
        if source_clean.lower() == "trimmed-big-book":
            source_clean = "Alcoholics Anonymous"

        passage_id = f"passage_{hash(res.source + str(idx)) & 0xFFFFFF}"
        excerpt_clean = re.sub(r"\s+", " ", res.excerpt[:80]).strip()

        if passage_id not in node_ids:
            nodes.append({
                "id": passage_id,
                "label": f"{source_clean}: {excerpt_clean}...",
                "type": "passage",
                "source": source_clean,
                "category": "literature",
                "excerpt": res.excerpt[:250],
            })
            node_ids.add(passage_id)

        edges.append({
            "source": central_id,
            "target": passage_id,
            "label": f"cite ({int(res.similarity * 100)}%)",
        })

        # Connect passage to matched recovery key terms
        excerpt_lower = res.excerpt.lower()
        matched_terms = [t for t in RECOVERY_TERMS if t in excerpt_lower and t != q.lower()][:3]
        for term in matched_terms:
            t_id = f"term_{term.replace(' ', '_')}"
            if t_id not in node_ids:
                nodes.append({
                    "id": t_id,
                    "label": term.title(),
                    "type": "term",
                    "category": "concept",
                })
                node_ids.add(t_id)

            edges.append({
                "source": passage_id,
                "target": t_id,
                "label": "contains term",
            })

    q_lower = q.lower()

    # Determine which steps to link. A *specific* step query ("step 9", "Step 4:
    # Fourth-Step Inventory", ...) must focus on THAT step only — otherwise every
    # step tap returns the same full 12-step wheel and clicking appears to do
    # nothing. A broad overview query ("The Twelve Steps", "the steps",
    # "inventory", ...) links the full wheel of 12.
    linked_steps: list[dict[str, Any]] = []
    step_num_match = re.search(r"step[\s_]*(\d{1,2})", q_lower)
    if step_num_match and 1 <= int(step_num_match.group(1)) <= 12:
        target_num = int(step_num_match.group(1))
        linked_steps = [
            s for s in CORE_RECOVERY_NODES
            if int(s["id"].split("_")[-1]) == target_num
        ]
    elif any(kw in q_lower for kw in ("step", "inventory", "twelve")):
        linked_steps = list(CORE_RECOVERY_NODES)

    for step_node in linked_steps:
        if step_node["id"] not in node_ids:
            nodes.append(step_node)
            node_ids.add(step_node["id"])
        edges.append({
            "source": central_id,
            "target": step_node["id"],
            "label": "relates to",
        })

    prompts = [
        f"How do I apply {q} in daily recovery?",
        f"What does the Big Book say about {q}?",
        f"What does the 12&12 teach about {q}?",
    ]
    for idx, prompt in enumerate(prompts):
        p_id = f"prompt_{hash(prompt) & 0xFFFFFF}"
        if p_id not in node_ids:
            nodes.append({
                "id": p_id,
                "label": prompt,
                "type": "prompt",
                "category": "followup",
            })
            node_ids.add(p_id)
        edges.append({
            "source": central_id,
            "target": p_id,
            "label": "explore",
        })

    # Data-driven enrichment (additive; no-op when ontology is None).
    if ontology:
        _enrich_from_ontology(ontology, q, nodes, edges, node_ids, central_id)

    return {
        "query": q,
        "nodes": nodes,
        "edges": edges,
    }

