#!/usr/bin/env python3
"""
Dump LDUs for a single PDF.

This runs the pipeline through Stage 3:
  triage -> extraction (with escalation) -> chunking -> validated List[LDU]

Example:
  uv run python scripts/dump_ldus.py path/to/document.pdf --limit 20

Writes (by default):
  .refinery/ldus/{document_id}.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents import run_triage
from src.agents.extractor import create_default_extraction_router
from src.agents.chunker import chunk_extracted_document

# Force CPU-only mode at the OS level to prevent CUDA sm_50 errors
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump LDUs for a PDF (Stage 3)")
    parser.add_argument("pdf", type=str, help="Path to PDF file")
    parser.add_argument("--limit", type=int, default=25, help="How many LDUs to print (default 25)")
    parser.add_argument(
        "--out",
        type=str,
        default=".refinery/ldus",
        help="Output directory for JSON (default .refinery/ldus)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    profile = run_triage(pdf_path)
    router = create_default_extraction_router()
    extracted_doc, result = router.extract(pdf_path, profile)
    if extracted_doc is None:
        print(f"Extraction failed: {result.notes or 'no extracted_document'}", file=sys.stderr)
        return 2

    ldus = chunk_extracted_document(extracted_doc)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{profile.document_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([ldu.model_dump() for ldu in ldus], f, ensure_ascii=False, indent=2)

    print(f"document_id={profile.document_id}")
    print(f"extraction_strategy={extracted_doc.strategy_used} confidence={extracted_doc.strategy_confidence:.2f}")
    print(f"ldus={len(ldus)} wrote={out_path}")
    print("")

    limit = max(0, int(args.limit))
    for i, ldu in enumerate(ldus[:limit], start=1):
        pages = [p.page_number for p in ldu.page_refs]
        snippet = (ldu.text or "").replace("\n", " ").strip()
        snippet = snippet[:160] + ("..." if len(snippet) > 160 else "")
        print(f"{i:03d} {ldu.id} type={ldu.content_type.value} pages={pages} hash={ldu.content_hash}")
        if ldu.parent_section_id:
            print(f"     parent_section_id={ldu.parent_section_id}")
        if snippet:
            print(f"     {snippet}")
        if ldu.relationships:
            print(f"     relationships={ldu.relationships}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

