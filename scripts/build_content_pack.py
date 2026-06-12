#!/usr/bin/env python3
"""Assembles the offline Android content pack zip file containing manifests, index, and FTS5 search.db."""

import os
import sys
import json
import sqlite3
import zipfile
import time
from pathlib import Path

def build_pack(documents_dir: str, output_dir: str, pack_version: int = 1):
    import tempfile
    
    documents_path = Path(documents_dir)
    manifests_path = documents_path / ".manifests"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    pack_file = output_path / f"library-v{pack_version}.scpack"
    print(f"Building content pack v{pack_version} at {pack_file}...")
    
    if not manifests_path.exists():
        print(f"Error: Manifests directory not found at {manifests_path}")
        sys.exit(1)
        
    manifest_files = list(manifests_path.glob("*.json"))
    if not manifest_files:
        print("Error: No manifest JSON files found.")
        sys.exit(1)
        
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db_path = Path(temp_dir) / "search.db"
        
        # Create search.db with FTS5
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE VIRTUAL TABLE blocks USING fts5(
                doc_id,
                block_id,
                heading,
                text
            );
        """)
        
        manifest_index = []
        
        # Process each manifest
        for m_file in manifest_files:
            try:
                with open(m_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to parse {m_file}, skipping. Error: {e}")
                continue
                
            doc_id = manifest.get("doc_id")
            title = manifest.get("title")
            author = manifest.get("author")
            category = manifest.get("category")
            blocks = manifest.get("blocks", [])
            sha256 = manifest.get("content_sha256")
            
            if not doc_id:
                print(f"Warning: Missing doc_id in {m_file}, skipping.")
                continue
                
            # Index entry
            manifest_index.append({
                "doc_id": doc_id,
                "title": title or doc_id,
                "author": author or "Unknown",
                "category": category or "uncategorized",
                "blocks_count": len(blocks),
                "sha256": sha256 or ""
            })
            
            # Populate FTS5 table
            current_heading = ""
            for b in blocks:
                b_type = b.get("type")
                if b_type == "heading":
                    current_heading = b.get("text", "")
                elif b_type in ("paragraph", "epigraph"):
                    cursor.execute(
                        "INSERT INTO blocks (doc_id, block_id, heading, text) VALUES (?, ?, ?, ?)",
                        (doc_id, b.get("id"), current_heading, b.get("text", ""))
                    )
                    
        conn.commit()
        conn.close()
        print(f"Populated SQLite search.db FTS5 table for {len(manifest_index)} documents.")
        
        # Pack metadata
        pack_meta = {
            "pack_version": pack_version,
            "schema_version": 1,
            "created_utc": int(time.time()),
            "doc_count": len(manifest_index)
        }
        
        # Zip assembly
        with zipfile.ZipFile(pack_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Write pack.json
            zipf.writestr("pack.json", json.dumps(pack_meta, indent=2))
            
            # Write manifest-index.json
            zipf.writestr("manifest-index.json", json.dumps(manifest_index, indent=2))
            
            # Write search.db
            zipf.write(temp_db_path, "search.db")
            
            # Write manifests
            for m_file in manifest_files:
                zipf.write(m_file, f"manifests/{m_file.name}")
        
    print(f"Successfully created content pack with {len(manifest_index)} manifests in {pack_file}")

if __name__ == "__main__":
    doc_dir = sys.argv[1] if len(sys.argv) > 1 else "documents"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "packs"
    build_pack(doc_dir, out_dir)
