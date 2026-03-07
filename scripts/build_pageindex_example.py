#!/usr/bin/env python3
"""Example: build PageIndex from LDUs and write .refinery/pageindex/{document_id}.json.
Run from repo root: uv run python scripts/build_pageindex_example.py
"""
from pathlib import Path

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.agents.indexer import build_page_index, write_pageindex, pageindex_query

def main() -> None:
    doc_id = "example_doc"
    page_count = 5
    # Fixture LDUs: two sections with headings
    def bbox() -> BoundingBox:
        return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)
    ldus = [
        LDU(
            id="ldu_1",
            document_id=doc_id,
            content_type=LDUContentType.SECTION_INTRO,
            text="1. Introduction",
            page_refs=[PageRef(document_id=doc_id, page_number=1)],
            bounding_boxes=[bbox()],
            token_count=2,
            content_hash=compute_content_hash("section_intro", "1. Introduction"),
        ),
        LDU(
            id="ldu_2",
            document_id=doc_id,
            content_type=LDUContentType.PARAGRAPH,
            text="This document describes the system.",
            page_refs=[PageRef(document_id=doc_id, page_number=1)],
            bounding_boxes=[bbox()],
            token_count=5,
            content_hash=compute_content_hash("paragraph", "This document describes the system."),
        ),
        LDU(
            id="ldu_3",
            document_id=doc_id,
            content_type=LDUContentType.SECTION_HEADER,
            text="2. Risk Factors",
            page_refs=[PageRef(document_id=doc_id, page_number=2)],
            bounding_boxes=[bbox()],
            token_count=2,
            content_hash=compute_content_hash("section_header", "2. Risk Factors"),
        ),
        LDU(
            id="ldu_4",
            document_id=doc_id,
            content_type=LDUContentType.PARAGRAPH,
            text="Risks include market and operational factors.",
            page_refs=[PageRef(document_id=doc_id, page_number=2)],
            bounding_boxes=[bbox()],
            token_count=6,
            content_hash=compute_content_hash("paragraph", "Risks include market and operational factors."),
        ),
    ]
    page_index = build_page_index(ldus, doc_id, page_count)
    out_dir = Path(".refinery/pageindex")
    path = write_pageindex(page_index, out_dir)
    print(f"Wrote PageIndex to {path}")
    print(f"Root: {page_index.root.title}, page_start={page_index.root.page_start}, page_end={page_index.root.page_end}")
    print(f"Child sections: {[s.title for s in page_index.root.child_sections]}")
    for s in page_index.root.child_sections:
        print(f"  - {s.id}: {s.title}, pages {s.page_start}-{s.page_end}, data_types_present={s.data_types_present}, ldu_ids={s.ldu_ids}")
    top = pageindex_query("risk factors", page_index=page_index, top_n=3)
    print(f"pageindex_query('risk factors', top_n=3): {[t.title for t in top]}")

if __name__ == "__main__":
    main()
