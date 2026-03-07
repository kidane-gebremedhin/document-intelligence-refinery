#!/usr/bin/env python3
"""
Minimal ingestion/query demo for the vector store (P4-T002).

Demo command (from repo root):
  uv run python scripts/demo_vector_store.py

Ingests 3 LDUs into .refinery/vector_store, then runs a query and prints the top hit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.data.vector_store import DEFAULT_VECTOR_STORE_PATH, ingest_ldus, search


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


def _ldu(id_: str, document_id: str, text: str, page: int = 1) -> LDU:
    return LDU(
        id=id_,
        document_id=document_id,
        content_type=LDUContentType.PARAGRAPH,
        text=text,
        page_refs=[PageRef(document_id=document_id, page_number=page)],
        bounding_boxes=[_bbox()],
        token_count=2,
        content_hash=compute_content_hash("paragraph", text),
    )


def main() -> None:
    path = Path(DEFAULT_VECTOR_STORE_PATH)
    ldus = [
        _ldu("ldu_1", "doc1", "Revenue for Q3 was four point two billion dollars.", page=1),
        _ldu("ldu_2", "doc1", "Risk factors include market volatility and regulation.", page=2),
        _ldu("ldu_3", "doc1", "The auditor issued an unqualified opinion.", page=3),
    ]
    n = ingest_ldus(ldus, path=path)
    print(f"Ingested {n} LDUs into {path}")

    results = search("revenue and quarterly results", top_k=1, path=path)
    if results:
        hit = results[0]
        print(f"Top hit: ldu_id={hit['ldu_id']}, document_id={hit['document_id']}")
        print(f"  content: {hit['content'][:80]}...")
        print(f"  page_refs={hit['page_refs']}, content_hash={hit['content_hash']}")
    else:
        print("No results.")


if __name__ == "__main__":
    main()
