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


def build_knowledge_graph(query: str, retriever: RAGRetriever | None = None) -> dict[str, Any]:
    """Build a node-and-edge graph payload centered around `query` with cross-connected terms and literature sources."""
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
    for step_node in CORE_RECOVERY_NODES:
        if any(term in q_lower for term in [step_node["id"].replace("_", " "), step_node["label"].lower(), "step", "inventory"]):
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

    return {
        "query": q,
        "nodes": nodes,
        "edges": edges,
    }

