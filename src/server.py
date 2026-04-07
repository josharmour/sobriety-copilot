"""Flask server with chat and indexing endpoints."""

import json
import os

from flask import Flask, Response, jsonify, request, send_from_directory

from src.inference.engine import InferenceEngine
from src.prompts.templates import NO_CONTEXT_TEMPLATE, USER_MESSAGE_TEMPLATE
from src.rag.indexer import RAGIndexer
from src.rag.retriever import RAGRetriever

app = Flask(__name__, static_folder="../static")

BASE_URL = os.environ.get("LLM_BASE_URL", "http://172.20.48.1:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "gemma4")
API_KEY = os.environ.get("LLM_API_KEY", "ollama")
DOCUMENTS_DIR = os.environ.get("DOCUMENTS_DIR", "documents")
RAG_DB_PATH = os.environ.get("RAG_DB_PATH", "rag_db")

engine = InferenceEngine(base_url=BASE_URL, model=MODEL, api_key=API_KEY)
retriever = RAGRetriever(db_path=RAG_DB_PATH)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "missing 'message' field"}), 400

    query = data["message"]
    history = data.get("history", [])
    categories = data.get("categories")
    results = retriever.retrieve(query, categories=categories or None)

    if results:
        context = retriever.format_context(results)
        prompt = USER_MESSAGE_TEMPLATE.format(context=context, question=query)
    else:
        prompt = NO_CONTEXT_TEMPLATE.format(question=query)

    sources = []
    for r in results:
        rel_path = os.path.relpath(r.source_path, DOCUMENTS_DIR) if r.source_path else r.source
        sources.append({
            "source": r.source,
            "similarity": round(r.similarity, 3),
            "url": f"/api/documents/{rel_path}",
            "excerpt": r.text,
        })

    def generate():
        # Send sources first
        yield f"data: {json.dumps({'sources': sources})}\n\n"
        try:
            for token in engine.stream(prompt, history=history):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: {\"done\": true}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/suggest")
def suggest():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])
    cats = request.args.get("categories", "")
    categories = [c.strip() for c in cats.split(",") if c.strip()] or None
    results = retriever.retrieve(q, top_k=10, categories=categories)
    seen = set()
    suggestions = []
    for r in results:
        # Extract a short topic phrase from the chunk
        # Use the first line (often a heading/title) or first clause
        first_line = r.text.strip().split("\n")[0].strip()
        # If first line is short enough, use it as the topic
        if len(first_line) <= 50:
            topic = first_line.rstrip(".")
        else:
            # Take first clause (split on comma, semicolon, dash, or period)
            for sep in [" - ", " — ", ". ", ", "]:
                if sep in first_line[:50]:
                    topic = first_line[: first_line.index(sep)]
                    break
            else:
                # Hard truncate at word boundary
                words = first_line[:45].rsplit(" ", 1)[0]
                topic = words + "..."
        if not topic or topic.lower() in seen:
            continue
        seen.add(topic.lower())
        suggestions.append({"text": topic, "source": r.source})
        if len(suggestions) >= 5:
            break
    return jsonify(suggestions)


@app.route("/api/categories")
def categories():
    """Return available document categories from folder structure."""
    abs_docs = os.path.abspath(DOCUMENTS_DIR)
    cats = []
    for entry in sorted(os.listdir(abs_docs)):
        if os.path.isdir(os.path.join(abs_docs, entry)) and not entry.startswith("."):
            label = entry.replace("_", " ").title()
            cats.append({"id": entry, "label": label})
    return jsonify(cats)


@app.route("/api/documents/<path:filepath>")
def serve_document(filepath):
    abs_docs = os.path.abspath(DOCUMENTS_DIR)
    return send_from_directory(abs_docs, filepath)


@app.route("/api/render/<path:filepath>")
def render_document(filepath):
    """Render an EPUB or PDF as HTML with optional text highlighting."""
    import html as html_mod

    abs_docs = os.path.abspath(DOCUMENTS_DIR)
    full_path = os.path.join(abs_docs, filepath)
    lower = full_path.lower()

    if not os.path.isfile(full_path):
        return "Not found", 404
    if not (lower.endswith(".epub") or lower.endswith(".pdf")):
        return "Unsupported format", 400

    highlight = request.args.get("highlight", "")

    import re
    CONTEXT_PAGES = 3  # pages before and after the match

    # Extract content based on format
    if lower.endswith(".epub"):
        from ebooklib import epub as epublib
        from bs4 import BeautifulSoup

        book = epublib.read_epub(full_path, options={"ignore_ncx": True})
        all_sections = []
        for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
            soup = BeautifulSoup(item.get_content(), "lxml")
            body = soup.find("body")
            if body:
                all_sections.append(str(body.decode_contents()))

        # Find which section contains the highlight, show nearby sections
        if highlight:
            words = highlight.split()[:12]
            pattern = r"[\s\S]{0,20}".join(re.escape(w) for w in words)
            match_idx = None
            for idx, section in enumerate(all_sections):
                if re.search(pattern, section):
                    match_idx = idx
                    break
            if match_idx is not None:
                start = max(0, match_idx - CONTEXT_PAGES)
                end = min(len(all_sections), match_idx + CONTEXT_PAGES + 1)
                all_sections = all_sections[start:end]

        content = '<hr style="border:none;border-top:1px solid #e5e7eb;margin:2rem 0;">'.join(all_sections)

    else:  # PDF
        import pdfplumber

        # First pass: find which page contains the highlight
        match_page = None
        if highlight:
            words = highlight.split()[:12]
            with pdfplumber.open(full_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    # Check if the first few words appear on this page
                    if all(w in text for w in words[:5]):
                        match_page = i
                        break

        # Second pass: only extract pages around the match
        with pdfplumber.open(full_path) as pdf:
            total = len(pdf.pages)
            if match_page is not None:
                start = max(0, match_page - CONTEXT_PAGES)
                end = min(total, match_page + CONTEXT_PAGES + 1)
            else:
                start = 0
                end = min(total, 2 * CONTEXT_PAGES + 1)

            pages = []
            for i in range(start, end):
                text = pdf.pages[i].extract_text()
                if text:
                    escaped_text = html_mod.escape(text).replace("\n", "<br>")
                    pages.append(
                        f'<div style="margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #e5e7eb;">'
                        f'<div style="font-size:0.7rem;color:#9ca3af;margin-bottom:0.5rem;">Page {i + 1} of {total}</div>'
                        f'<div>{escaped_text}</div></div>'
                    )
        content = "\n".join(pages)

    # Highlight excerpt text
    if highlight:
        words = highlight.split()[:15]
        pattern = r"[\s\S]{0,10}".join(re.escape(w) for w in words)
        match = re.search(pattern, content)
        if match:
            start = match.start()
            end = content.find(".", start + len(match.group()))
            if end == -1 or end - start > 1500:
                end = start + len(match.group())
            snippet = content[start:end + 1]
            highlighted = f'<span id="hl" style="background:#d4f5e9;padding:2px 4px;border-radius:3px;">{snippet}</span>'
            content = content[:start] + highlighted + content[end + 1:]

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{
  font-family: Georgia, "Times New Roman", serif;
  max-width: 720px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
  line-height: 1.8;
  color: #1a1a2e;
  font-size: 1rem;
  background: #fff;
}}
h1,h2,h3,h4 {{ font-family: -apple-system, sans-serif; color: #264653; margin-top: 1.5em; }}
p {{ margin: 0.75em 0; }}
#hl {{ scroll-margin-top: 100px; }}
</style></head>
<body>{content}
<script>
  const hl = document.getElementById('hl');
  if (hl) hl.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
</script>
</body></html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/index", methods=["POST"])
def index_documents():
    indexer = RAGIndexer(db_path=RAG_DB_PATH)
    directory = DOCUMENTS_DIR
    data = request.get_json(silent=True)
    if data and "directory" in data:
        directory = data["directory"]

    if not os.path.isdir(directory):
        return jsonify({"error": f"directory not found: {directory}"}), 400

    try:
        indexer.clear()
        count = indexer.index_directory(directory)
    except Exception as e:
        return jsonify({"error": f"indexing failed: {e}"}), 500

    # Reload retriever to pick up new documents
    global retriever
    retriever = RAGRetriever(db_path=RAG_DB_PATH)

    return jsonify({"indexed_chunks": count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
