#!/usr/bin/env python3
"""
Inspect the vector store (ChromaDB) and fact table (SQLite) under .refinery.

  uv run python scripts/inspect_refinery_data.py
  uv run python scripts/inspect_refinery_data.py --refinery-dir .refinery --vector-limit 5 --fact-limit 20
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def inspect_vector_store(path: Path, collection_name: str = "ldu_chunks", limit: int = 10) -> None:
    """Print count, document_ids, and sample entries from the ChromaDB vector store."""
    if not path.exists():
        print(f"Vector store not found: {path}")
        return
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(path=str(path.resolve()), settings=Settings(anonymized_telemetry=False))
        coll = client.get_collection(name=collection_name)
    except Exception as e:
        print(f"Vector store error: {e}")
        return

    total = coll.count()
    print(f"--- Vector store: {path} (collection: {collection_name}) ---")
    print(f"Total LDUs: {total}")

    if total == 0:
        return

    # Get all ids and metadatas to derive unique document_ids
    result = coll.get(include=["metadatas", "documents"], limit=min(total, 1000))
    doc_ids = set()
    if result.get("metadatas"):
        for m in result["metadatas"]:
            if isinstance(m, dict) and m.get("document_id"):
                doc_ids.add(m["document_id"])
    print(f"Document IDs: {sorted(doc_ids)}")

    # Sample entries
    n = min(limit, total)
    result = coll.get(include=["metadatas", "documents"], limit=n)
    ids = result.get("ids") or []
    metadatas = result.get("metadatas") or []
    documents = result.get("documents") or []

    print(f"\nSample entries (first {n}):")
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) else {}
        doc = documents[i] if i < len(documents) else ""
        content_preview = (doc or "")[:120].replace("\n", " ") + ("..." if len(doc or "") > 120 else "")
        print(f"  [{i+1}] id={ids[i]} document_id={meta.get('document_id')} page_refs={meta.get('page_refs')} content_hash={meta.get('content_hash','')[:12]}...")
        print(f"      content: {content_preview}")


def inspect_fact_table(path: Path, limit: int = 20) -> None:
    """Print row count and sample rows from the SQLite fact table."""
    if not path.exists():
        print(f"\nFact table not found: {path}")
        return
    print(f"\n--- Fact table: {path} ---")
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM facts")
        count = cur.fetchone()[0]
        print(f"Total rows: {count}")

        if count == 0:
            return

        cur = conn.execute(
            "SELECT document_id, entity, metric, value, unit, period, source_page FROM facts LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]
        print(f"\nSample rows (first {len(rows)}):")
        for i, row in enumerate(rows):
            d = dict(zip(col_names, row))
            print(f"  [{i+1}] {d}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect vector store and fact table under a refinery directory")
    parser.add_argument(
        "--refinery-dir",
        type=Path,
        default=Path(".refinery"),
        help="Refinery base directory (default: .refinery)",
    )
    parser.add_argument(
        "--vector-limit",
        type=int,
        default=10,
        help="Max sample entries to print from vector store (default: 10)",
    )
    parser.add_argument(
        "--fact-limit",
        type=int,
        default=20,
        help="Max rows to print from fact table (default: 20)",
    )
    parser.add_argument(
        "--vector-only",
        action="store_true",
        help="Only inspect vector store",
    )
    parser.add_argument(
        "--fact-only",
        action="store_true",
        help="Only inspect fact table",
    )
    args = parser.parse_args()

    base = args.refinery_dir.resolve()
    vs_path = base / "vector_store"
    fact_path = base / "fact_table.db"

    if not args.fact_only:
        inspect_vector_store(vs_path, limit=args.vector_limit)
    if not args.vector_only:
        inspect_fact_table(fact_path, limit=args.fact_limit)

    return 0


if __name__ == "__main__":
    sys.exit(main())
