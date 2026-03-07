#!/usr/bin/env python3
"""
Run the full Refinery Pipeline for a single PDF (5 stages):
  1) triage -> DocumentProfile
  2) extraction router -> ExtractedDocument (fast_text/layout/vision)
  3) chunking -> LDUs (validated)
  4) PageIndex builder -> .refinery/pageindex/{document_id}.json
  5) data layer ingestion -> vector store + FactTable

Example:
  uv run python scripts/run_pipeline.py path/to/document.pdf
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
from src.agents.indexer import build_page_index, write_pageindex, get_default_summarizer, DEFAULT_PAGEINDEX_DIR
from src.data.vector_store import ingest_ldus as vector_store_ingest_ldus, DEFAULT_VECTOR_STORE_PATH
from src.data.fact_table import extract_facts_from_ldus, DEFAULT_FACT_TABLE_PATH, init_fact_table

# Force CPU-only mode at the OS level to prevent CUDA sm_50 errors
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"


def _write_profile(profile_json: str, document_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document_id}.json"
    path.write_text(profile_json, encoding="utf-8")
    return path


def _write_ldus(ldus, document_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document_id}.json"
    path.write_text(json.dumps([l.model_dump() for l in ldus], ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full 5-stage Refinery pipeline for one PDF")
    parser.add_argument("pdf", type=str, help="Path to PDF file")
    parser.add_argument("--out", type=str, default=".refinery", help="Base output dir (default .refinery)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    base = Path(args.out)
    profiles_dir = base / "profiles"
    ldus_dir = base / "ldus"
    pageindex_dir = base / "pageindex"
    vector_store_dir = base / "vector_store"
    fact_table_path = base / "fact_table.db"

    # Stage 1: triage
    profile = run_triage(pdf_path)
    profile_path = _write_profile(profile.to_profile_json(), profile.document_id, profiles_dir)
    print(f"[stage1] profile: {profile_path}")

    # Stage 2: extraction
    router = create_default_extraction_router(ledger_path=base / "extraction_ledger.jsonl")
    extracted_doc, extraction_result = router.extract(pdf_path, profile)
    if extracted_doc is None:
        print(f"[stage2] extraction failed: {extraction_result.notes or 'no extracted_document'}", file=sys.stderr)
        return 2
    print(f"[stage2] extracted: strategy={extracted_doc.strategy_used} confidence={extracted_doc.strategy_confidence:.2f}")

    # Stage 3: chunking
    ldus = chunk_extracted_document(extracted_doc)
    ldus_path = _write_ldus(ldus, profile.document_id, ldus_dir)
    print(f"[stage3] ldus: {len(ldus)} wrote {ldus_path}")

    # Stage 4: pageindex (LLM summaries when REFINERY_SUMMARIZER_ENABLED=1)
    page_count = extracted_doc.pages
    summarizer = get_default_summarizer()
    page_index = build_page_index(ldus, profile.document_id, page_count, summarizer=summarizer)
    pageindex_path = write_pageindex(page_index, pageindex_dir)
    print(f"[stage4] pageindex: {pageindex_path}")

    # Stage 5: data layer ingestion (vector store + FactTable)
    vector_store_ingest_ldus(ldus, path=vector_store_dir)
    print(f"[stage5] vector_store: ingested {len(ldus)} into {vector_store_dir}")

    init_fact_table(fact_table_path)
    facts = extract_facts_from_ldus(ldus, path=fact_table_path, enabled=True, table_only=False)
    print(f"[stage5] fact_table: inserted {facts} fact(s) into {fact_table_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

