#!/usr/bin/env python3
"""
Run the LangGraph query agent: one question → answer + ProvenanceChain.

Uses the vector store, PageIndex, and FactTable under a refinery directory
(by default .refinery/). Run the full pipeline first to populate them:

  uv run python scripts/run_pipeline.py path/to/document.pdf

Then run this script with a question. No hardcoded document IDs or sample data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tracing import ensure_env_loaded
from src.agents.query_agent import query


def _document_name_resolver_from_file(path: Path | None):
    """Build resolver: if path exists and is JSON {document_id: name}, use it; else identity."""
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
        description="Run the LangGraph query agent (question → answer + ProvenanceChain)."
    )
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Natural-language question (optional; prompt if omitted).",
    )
    parser.add_argument(
        "--refinery-dir",
        type=Path,
        default=Path(".refinery"),
        help="Base directory for vector_store, pageindex, fact_table (default: .refinery)",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=None,
        help="Restrict search to this document ID (optional; search all if omitted).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Max number of LDU hits to use (default: 10).",
    )
    parser.add_argument(
        "--document-names",
        type=Path,
        default=None,
        help="JSON file mapping document_id → display name (default: <refinery-dir>/document_names.json if present).",
    )
    args = parser.parse_args()

    refinery = args.refinery_dir.resolve()
    vector_store_path = refinery / "vector_store"
    pageindex_dir = refinery / "pageindex"
    fact_table_path = refinery / "fact_table.db"

    question = args.question
    if question is None or not question.strip():
        question = input("Question: ").strip() or "What is this document about?"
    else:
        question = question.strip()

    doc_names_path = args.document_names
    if doc_names_path is None:
        doc_names_path = refinery / "document_names.json"
    resolver = _document_name_resolver_from_file(doc_names_path)

    result = query(
        question,
        document_id=args.document_id,
        vector_store_path=vector_store_path,
        fact_table_path=fact_table_path,
        pageindex_dir=pageindex_dir,
        top_k=args.top_k,
        document_name_resolver=resolver,
    )

    print(f"Questiion: {question}")
    print("--- Answer ---")
    print(result["answer"])
    print("\n--- Provenance (verified: {}) ---".format(result["verified"]))
    chain = result.get("provenance_chain") or {}
    items = chain.get("items") or []
    for i, cit in enumerate(items, 1):
        name = cit.get("document_name", "")
        page = cit.get("page_number", "")
        bbox = cit.get("bbox") or {}
        bbox_str = f"bbox=[{bbox.get('x0')},{bbox.get('y0')},{bbox.get('x1')},{bbox.get('y1')}]" if bbox else "bbox=N/A"
        h = (cit.get("content_hash") or "")[:12]
        print(f"  {i}. {name} p.{page} {bbox_str} content_hash={h}...")
    if not items:
        print("  (no citations)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
