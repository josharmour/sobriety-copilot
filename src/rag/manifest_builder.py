import os
import re
import json
import hashlib
from typing import Any

from src.render_cache import extract_pdf_render_payload
from src.rag.document_processor import _detect_running_headers, _ALWAYS_STRIP_RE
from src.rag.text_repair import (
    collapse_doubled_layers,
    repair_hyphenation,
    repair_ligatures,
    reflow_paragraphs
)
from src.rag.block_classifier import classify_block

def get_manifest_path(source_path: str, documents_dir: str) -> str:
    """
    Get the absolute path where the manifest for a document will be stored.
    """
    base = os.path.splitext(os.path.basename(source_path))[0]
    if " - " in base:
        title, _ = base.split(" - ", 1)
    else:
        title = base
    doc_id = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return os.path.join(documents_dir, ".manifests", f"{doc_id}.json")


def should_rebuild(source_path: str, documents_dir: str, current_extractor_version: int = 1) -> bool:
    """
    Check if a manifest should be rebuilt (based on SHA256 of source and extractor version).
    """
    manifest_path = get_manifest_path(source_path, documents_dir)
    if not os.path.exists(manifest_path):
        return True
    
    # Compute current sha256
    sha = hashlib.sha256()
    with open(source_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    content_sha256 = sha.hexdigest()
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return (
            manifest.get("content_sha256") != content_sha256 or
            manifest.get("extractor_version") != current_extractor_version
        )
    except Exception:
        return True


def detect_manifest_running_headers(pages: list[str], threshold: int = 3) -> set[str]:
    """
    Detect repeated header patterns across pages, resolving doubled layers first.
    """
    from collections import Counter
    pattern_counts: Counter[str] = Counter()
    for page in pages:
        lines = page.split("\n")
        seen_on_page = set()
        candidate_lines = lines[:3] + lines[-2:]
        for line in candidate_lines:
            stripped = line.strip()
            # Collapse doubled layers first so that the length limit of 80 works on the collapsed version
            collapsed = collapse_doubled_layers(stripped)
            if not collapsed or len(collapsed) > 80:
                continue
            normalized = re.sub(r"\d+", "#", collapsed)
            if normalized not in seen_on_page:
                seen_on_page.add(normalized)
                pattern_counts[normalized] += 1
                
    return {p for p, count in pattern_counts.items() if count >= threshold}


def build_manifest(source_path: str, category: str) -> dict[str, Any]:
    """
    Build a canonical manifest for a PDF document.
    """
    base = os.path.splitext(os.path.basename(source_path))[0]
    if " - " in base:
        title, author = base.split(" - ", 1)
    else:
        title = base
        author = "Unknown"
    
    # Stable doc_id slug
    doc_id = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    
    # Compute SHA256
    sha = hashlib.sha256()
    with open(source_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    content_sha256 = sha.hexdigest()
    
    # Load PDF text pages
    render_payload = extract_pdf_render_payload(source_path)
    raw_pages = render_payload["page_text"]
    
    # Detect running headers across the entire document
    running_headers = detect_manifest_running_headers(raw_pages)
    
    # Clean pages (page-by-page)
    headers_stripped_count = 0
    doubled_layer_pages_count = 0
    cleaned_pages = []
    printed_pages = []
    
    for idx, page_text in enumerate(raw_pages):
        physical_page = idx + 1
        lines = page_text.split("\n")
        
        # Detect printed page
        candidate_lines = lines[:3] + lines[-2:]
        printed_page = None
        for line in candidate_lines:
            stripped = line.strip()
            collapsed_cand = collapse_doubled_layers(stripped)
            if re.match(r'^\d+$', collapsed_cand):
                printed_page = int(collapsed_cand)
                break
        printed_pages.append(printed_page)
        
        cleaned_lines = []
        page_had_doubled_collapse = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            
            # Collapse doubled character layer first
            collapsed = collapse_doubled_layers(stripped)
            if collapsed != stripped:
                page_had_doubled_collapse = True
            
            # Header/footer strip
            is_header_footer = (i < 3 or i >= len(lines) - 2)
            if is_header_footer:
                if _ALWAYS_STRIP_RE.match(collapsed):
                    headers_stripped_count += 1
                    continue
                normalized = re.sub(r"\d+", "#", collapsed)
                if normalized in running_headers:
                    headers_stripped_count += 1
                    continue
            
            cleaned_lines.append(collapsed)
            
        if page_had_doubled_collapse:
            doubled_layer_pages_count += 1
            
        cleaned_pages.append(cleaned_lines)
        
    # Reassemble pages with markers to run global repairs
    combined_text_parts = []
    for idx, lines in enumerate(cleaned_pages):
        physical_page = idx + 1
        combined_text_parts.append(f"===PAGE-START-{physical_page}===")
        combined_text_parts.extend(lines)
        
    combined_text = "\n".join(combined_text_parts)
    
    # Count hyphen repairs using the same logic before calling it
    words = re.findall(r'\b[a-zA-Z]{2,}\b', combined_text)
    word_counts_hyphen = {}
    for w in words:
        wl = w.lower()
        word_counts_hyphen[wl] = word_counts_hyphen.get(wl, 0) + 1
    valid_words = {w for w, count in word_counts_hyphen.items() if count >= 2}
    
    hyphen_pattern = r'\b([a-zA-Z]+)-\s*(\r?\n\s*|\s+)([a-zA-Z]+)\b'
    hyphen_repairs_count = 0
    for m in re.finditer(hyphen_pattern, combined_text):
        part1 = m.group(1)
        part2 = m.group(3)
        combined_word = part1 + part2
        is_part1_word = part1.lower() in valid_words
        is_part2_word = part2.lower() in valid_words
        if combined_word.lower() in valid_words or not is_part1_word or not is_part2_word:
            hyphen_repairs_count += 1
            
    repaired_text = repair_hyphenation(combined_text)
    
    # Count ligature repairs
    word_counts = {}
    for w in re.findall(r'\b[a-zA-Z]+\b', repaired_text):
        wl = w.lower()
        word_counts[wl] = word_counts.get(wl, 0) + 1
        
    allowlist = {
        "first", "sufficient", "fellowship", "influence", "conflict", "afflict",
        "definition", "define", "final", "finally", "difficult", "difficulty",
        "flourish", "flat", "flight", "flow", "flower", "fluid", "fly", "flying",
        "official", "officer", "office", "efficiency", "efficient", "affliction",
        "conflict", "inflict", "conflate", "inflate", "deflate", "flu", "flush",
        "find", "finds", "finding", "findings", "terrific", "profit", "profitable",
        "flame", "fled", "flee", "fleet", "flesh", "float", "flock", "flood", "floor",
        "flowed", "flows", "flung", "flurry", "flute", "reflect", "reflection"
    }
    ligature_pattern = r'\b(\w*f[il])\s+(\w+)\b'
    ligature_repairs_count = 0
    for m in re.finditer(ligature_pattern, repaired_text):
        part1 = m.group(1)
        part2 = m.group(2)
        combined_word = part1 + part2
        combined_lower = combined_word.lower()
        if combined_lower in allowlist or word_counts.get(combined_lower, 0) >= 2:
            ligature_repairs_count += 1
            
    repaired_text = repair_ligatures(repaired_text)
    
    # Split back into pages
    repaired_pages_raw = repaired_text.split("===PAGE-START-")
    repaired_pages = {}
    for part in repaired_pages_raw:
        if not part.strip():
            continue
        lines = part.split("\n")
        header_line = lines[0]
        physical_page = int(header_line.split("===")[0])
        page_lines = lines[1:]
        if page_lines and not page_lines[-1]:
            page_lines.pop()
        repaired_pages[physical_page] = page_lines
        
    # Build manifest blocks
    blocks = []
    block_ordinal = 1
    garbage_lines_count = 0
    toc_blocks_count = 0
    
    for idx in range(len(raw_pages)):
        physical_page = idx + 1
        page_lines = repaired_pages.get(physical_page, [])
        printed_page = printed_pages[idx]
        
        # Reflow paragraphs
        reflowed_paras = reflow_paragraphs(page_lines)
        
        for para in reflowed_paras:
            if not para.strip():
                continue
                
            # Estimate position
            first_line = para.split("\n")[0].strip()
            line_idx = 0
            for l_i, l in enumerate(page_lines):
                if first_line in l:
                    line_idx = l_i
                    break
            position_on_page = line_idx / max(1, len(page_lines))
            
            block_type = classify_block(para, position_on_page, running_headers)
            
            if block_type == "garbage":
                garbage_lines_count += 1
            elif block_type == "toc":
                toc_blocks_count += 1
                
            block_id = f"b{block_ordinal:05d}"
            block_ordinal += 1
            
            block_dict = {
                "id": block_id,
                "type": block_type,
                "text": para,
                "printed_page": printed_page,
                "physical_page": physical_page
            }
            
            if block_type == "heading":
                if re.match(r'^(Part|Section)\b', para, re.IGNORECASE):
                    block_dict["level"] = 1
                elif re.match(r'^(Step|Chapter|Tradition)\b', para, re.IGNORECASE):
                    block_dict["level"] = 2
                else:
                    block_dict["level"] = 3
                    
            blocks.append(block_dict)
            
    total_blocks_count = len(blocks)
    ocr_recommended = False
    if total_blocks_count > 0:
        garbage_ratio = garbage_lines_count / total_blocks_count
        if garbage_ratio > 0.05:
            ocr_recommended = True
            
    manifest = {
        "schema_version": 1,
        "doc_id": doc_id,
        "source_file": source_path,
        "content_sha256": content_sha256,
        "extractor_version": 1,
        "title": title,
        "author": author,
        "category": category,
        "blocks": blocks,
        "lint": {
            "doubled_layer_pages": doubled_layer_pages_count,
            "headers_stripped": headers_stripped_count,
            "hyphen_repairs": hyphen_repairs_count,
            "ligature_repairs": ligature_repairs_count,
            "garbage_lines_removed": garbage_lines_count,
            "toc_blocks": toc_blocks_count,
            "ocr_recommended": ocr_recommended
        }
    }
    return manifest


def write_manifest(manifest: dict[str, Any], documents_dir: str) -> str:
    """
    Write a manifest dictionary to JSON in documents/.manifests/<doc_id>.json
    """
    doc_id = manifest["doc_id"]
    manifests_dir = os.path.join(documents_dir, ".manifests")
    os.makedirs(manifests_dir, exist_ok=True)
    manifest_path = os.path.join(manifests_dir, f"{doc_id}.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path
