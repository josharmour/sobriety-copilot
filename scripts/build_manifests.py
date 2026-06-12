#!/usr/bin/env python3
import os
import sys
import json
import re
from typing import Any

# Ensure src can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.rag.manifest_builder import build_manifest, write_manifest, should_rebuild, get_manifest_path

def find_files(documents_dir: str) -> list[str]:
    """
    Find all PDF and EPUB files under documents_dir, skipping hidden/thumb directories.
    """
    files = []
    for root, dirs, filenames in os.walk(documents_dir):
        # Modify dirs in-place to skip hidden folders
        dirs[:] = [d for d in dirs if d not in ("@eaDir", ".manifests", ".git", "__pycache__")]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in (".pdf", ".epub"):
                files.append(os.path.join(root, f))
    return files


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_manifests.py <documents_dir>")
        sys.exit(1)
        
    documents_dir = sys.argv[1]
    if not os.path.isdir(documents_dir):
        print(f"Error: Directory '{documents_dir}' does not exist.")
        sys.exit(1)
        
    print(f"Scanning for books in {documents_dir}...")
    files = find_files(documents_dir)
    print(f"Found {len(files)} books.")
    
    reports = []
    ocr_recommended_any = False
    
    for file_path in files:
        rel_path = os.path.relpath(file_path, documents_dir)
        parts = rel_path.split(os.sep)
        category = parts[0] if len(parts) > 1 else "other"
        
        rebuilt = False
        try:
            if should_rebuild(file_path, documents_dir):
                rebuilt = True
                print(f"Building: {rel_path}...")
                manifest = build_manifest(file_path, category)
                write_manifest(manifest, documents_dir)
            else:
                manifest_path = get_manifest_path(file_path, documents_dir)
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    
            lint = manifest["lint"]
            total_blocks = len(manifest["blocks"])
            garbage_ratio = (lint["garbage_lines_removed"] / max(1, total_blocks))
            ocr_rec = lint["ocr_recommended"]
            
            if ocr_rec:
                ocr_recommended_any = True
                
            status_str = "REBUILT" if rebuilt else "SKIPPED"
            print(f"[{status_str}] {manifest['title']} ({manifest['doc_id']}): "
                  f"doubled_pages={lint['doubled_layer_pages']}, "
                  f"headers_stripped={lint['headers_stripped']}, "
                  f"hyphens={lint['hyphen_repairs']}, "
                  f"ligatures={lint['ligature_repairs']}, "
                  f"garbage={lint['garbage_lines_removed']}, "
                  f"ocr_recommended={ocr_rec}")
                  
            reports.append({
                "title": manifest["title"],
                "doc_id": manifest["doc_id"],
                "garbage_ratio": garbage_ratio,
                "ocr_recommended": ocr_rec,
                "total_blocks": total_blocks,
                "garbage_blocks": lint["garbage_lines_removed"]
            })
            
        except Exception as e:
            print(f"Error processing {rel_path}: {e}")
            import traceback
            traceback.print_exc()
            
    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Title':<45} | {'Blocks':<8} | {'Garbage':<8} | {'Garbage Ratio':<15} | {'OCR Recommended':<15}")
    print("-" * 90)
    
    # Sort reports by garbage ratio descending
    reports.sort(key=lambda r: r["garbage_ratio"], reverse=True)
    
    for r in reports:
        print(f"{r['title'][:44]:<45} | {r['total_blocks']:<8} | {r['garbage_blocks']:<8} | {r['garbage_ratio']:.2%}        | {str(r['ocr_recommended']):<15}")
    print("=" * 90)
    
    if ocr_recommended_any:
        print("\nWarning: Some manifests have high garbage ratios and OCR is recommended.")
        sys.exit(1)
    else:
        print("\nAll manifests built successfully with clean lint ratios.")
        sys.exit(0)

if __name__ == '__main__':
    main()
