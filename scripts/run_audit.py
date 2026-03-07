#!/usr/bin/env python3
"""
Audit mode: verify a claim against the corpus. Returns either verified (with source citations)
or "not found / unverifiable". Citations include document_name, page_number, bbox, content_hash.

Example:
  uv run python scripts/run_audit.py "The report states revenue was $4.2B in Q3"
  uv run python scripts/run_audit.py "Revenue was $4.2B" --refinery-dir .refinery --document-id abc123
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tracing import ensure_env_loaded
from src.agents.audit import audit


def _resolver_from_file(path: Path | None):
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return lambda doc_id: data.get(doc_id, doc_id)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def main() -> int:
    ensure_env_loaded()
    parser = argparse.ArgumentParser(
        description="Audit mode: verify a claim → ProvenanceChain or unverifiable."
    )
    parser.add_argument("claim", type=str, help="Claim to verify (e.g. 'Revenue was $4.2B in Q3')")
    parser.add_argument(
        "--refinery-dir",
        type=Path,
        default=Path(".refinery"),
        help="Base directory for vector_store and fact_table (default: .refinery)",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=None,
        help="Restrict to this document ID (optional)",
    )
    parser.add_argument(
        "--document-names",
        type=Path,
        default=None,
        help="JSON file mapping document_id → display name",
    )
    args = parser.parse_args()

    vector_store_path = args.refinery_dir.resolve() / "vector_store"
    fact_table_path = args.refinery_dir.resolve() / "fact_table.db"
    doc_names_path = args.document_names or (args.refinery_dir / "document_names.json")
    resolver = _resolver_from_file(doc_names_path)

    result = audit(
        args.claim,
        document_id=args.document_id,
        vector_store_path=vector_store_path,
        fact_table_path=fact_table_path,
        document_name_resolver=resolver,
    )

    print(result.response_text)
    print("\nStatus:", result.status)
    print("Verified:", result.verified)
    print("\nCitations (document_name, page_number, bbox, content_hash):")
    for i, item in enumerate(result.chain.items, 1):
        b = item.bbox
        bbox_str = f"[{b.x0},{b.y0},{b.x1},{b.y1}]" if b else "N/A"
        print(f"  {i}. {item.document_name} p.{item.page_number} bbox={bbox_str} hash={item.content_hash[:12]}...")
    if not result.chain.items:
        print("  (none — claim not found / unverifiable)")
    return 0 if result.verified else 1


if __name__ == "__main__":
    sys.exit(main())
