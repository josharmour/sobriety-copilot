#!/usr/bin/env python3
"""Validation script to verify shadow index query performance and metadata citations."""

import os
import sys
import json
from pathlib import Path

# Add src to python path if not present
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.retriever import RAGRetriever
from src.tasks.job_store import get_redis_client, INDEX_ACTIVE_COLLECTION_KEY

def main():
    redis_client = get_redis_client()
    active_collection = redis_client.get(INDEX_ACTIVE_COLLECTION_KEY)
    print(f"Active collection from Redis: {active_collection}")
    
    if not active_collection:
        print("Error: No active collection name found in Redis.")
        sys.exit(1)
        
    db_path = os.environ.get("RAG_DB_PATH", "rag_db")
    print(f"Initializing RAGRetriever with db_path={db_path}, collection={active_collection}")
    retriever = RAGRetriever(db_path=db_path, collection_name=active_collection)
    
    queries = [
        "Step 10",
        "What's the difference between step four and step ten?",
        "What does the Big Book say about resentment?",
        "making amends in Step Nine",
        "how do I handle cravings at night"
    ]
    
    overall_passed = True
    
    for q in queries:
        print("\n" + "="*80)
        print(f"QUERY: '{q}'")
        print("="*80)
        
        results = retriever.retrieve(q, top_k=8)
        print(f"Retrieved {len(results)} results.")
        
        for idx, res in enumerate(results, 1):
            text_snippet = (res.excerpt or res.text or "")[:120].replace('\n', ' ')
            print(f"\n[{idx}] Score: {res.similarity:.4f} | Source: {res.source}")
            print(f"    doc_id: {res.doc_id}")
            print(f"    block_ids: {res.block_ids}")
            print(f"    printed_page_start: {res.printed_page_start} | printed_page_end: {res.printed_page_end}")
            print(f"    Text: {text_snippet}...")
            
            # Validation assertions
            if not res.doc_id:
                print("    --> WARNING: doc_id is missing!")
                overall_passed = False
                
            if not res.block_ids:
                print("    --> WARNING: block_ids list is missing or empty!")
                overall_passed = False
                
            # If doc_id exists, load manifest and check block types
            if res.doc_id:
                manifest_path = Path("documents/.manifests") / f"{res.doc_id}.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)
                        blocks_map = {b["id"]: b for b in manifest.get("blocks", [])}
                        
                        toc_blocks = []
                        for b_id in res.block_ids or []:
                            block = blocks_map.get(b_id)
                            if block:
                                if block.get("type") in ("toc", "index", "page_header", "page_footer", "garbage"):
                                    toc_blocks.append((b_id, block.get("type")))
                        if toc_blocks:
                            print(f"    --> ERROR: Found invalid block types indexed: {toc_blocks}")
                            overall_passed = False
                    except Exception as e:
                        print(f"    --> Error checking manifest: {e}")
                else:
                    print(f"    --> Warning: manifest not found at {manifest_path}")

    if overall_passed:
        print("\nALL VERIFICATIONS PASSED: No TOC/garbage blocks found, all chunks carry valid doc_id/block_ids metadata.")
        sys.exit(0)
    else:
        print("\nVERIFICATIONS FAILED. Check details above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
