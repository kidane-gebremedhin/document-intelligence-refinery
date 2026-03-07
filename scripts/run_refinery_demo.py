#!/usr/bin/env python3
"""
Run the Refinery pipeline in the exact 4-step sequence, then answer a question with provenance.

  Step 1: The Triage       — DocumentProfile output
  Step 2: The Extraction   — Extract + chunk to LDUs
  Step 3: The PageIndex    — Build page index and ingest (vector store + FactTable)
  Step 4: Query with Provenance — Natural-language question → answer + ProvenanceChain (page + bbox)

Example:
  uv run python scripts/run_refinery_demo.py path/to/document.pdf "What was revenue in Q3?"
  uv run python scripts/run_refinery_demo.py path/to/document.pdf
  (prompts for a question after Step 3)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tracing import ensure_env_loaded
from src.agents import run_triage
from src.agents.extractor import create_default_extraction_router
from src.agents.chunker import chunk_extracted_document
from src.agents.indexer import build_page_index, write_pageindex, get_default_summarizer
from src.agents.query_agent import query
from src.data.vector_store import ingest_ldus as vector_store_ingest_ldus
from src.data.fact_table import extract_facts_from_ldus, init_fact_table

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")


def _write_profile(profile_json: str, document_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document_id}.json"
    path.write_text(profile_json, encoding="utf-8")
    return path


def _write_ldus(ldus, document_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document_id}.json"
    path.write_text(
        json.dumps([l.model_dump() for l in ldus], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _document_name_resolver_from_file(refinery_dir: Path, doc_id: str) -> str:
    path = refinery_dir / "document_names.json"
    if not path.exists():
        return doc_id
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get(doc_id, doc_id)
    except (json.JSONDecodeError, OSError):
        pass
    return doc_id


def main() -> int:
    ensure_env_loaded()
    parser = argparse.ArgumentParser(
        description="Run Refinery: Triage → Extraction → PageIndex → Query with Provenance"
    )
    parser.add_argument("pdf", type=str, help="Path to PDF file")
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Natural-language question (optional; prompt after Step 3 if omitted)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".refinery"),
        help="Base output dir (default .refinery)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    base = args.out.resolve()
    profiles_dir = base / "profiles"
    ldus_dir = base / "ldus"
    pageindex_dir = base / "pageindex"
    vector_store_dir = base / "vector_store"
    fact_table_path = base / "fact_table.db"

    # ---------- Step 1: The Triage ----------
    print("\n=== Step 1: The Triage ===")
    profile = run_triage(pdf_path)
    profile_path = _write_profile(profile.to_profile_json(), profile.document_id, profiles_dir)
    print(f"DocumentProfile written: {profile_path}")
    print(profile.to_profile_json())

    # ---------- Step 2: The Extraction ----------
    print("\n=== Step 2: The Extraction ===")
    router = create_default_extraction_router(ledger_path=base / "extraction_ledger.jsonl")
    extracted_doc, extraction_result = router.extract(pdf_path, profile)
    if extracted_doc is None:
        print(
            f"Extraction failed: {extraction_result.notes or 'no extracted_document'}",
            file=sys.stderr,
        )
        return 2
    ldus = chunk_extracted_document(extracted_doc)
    ldus_path = _write_ldus(ldus, profile.document_id, ldus_dir)
    print(f"Extracted and chunked: {len(ldus)} LDUs → {ldus_path}")

    # ---------- Step 3: The PageIndex ----------
    print("\n=== Step 3: The PageIndex ===")
    page_count = extracted_doc.pages
    summarizer = get_default_summarizer()
    page_index = build_page_index(ldus, profile.document_id, page_count, summarizer=summarizer)
    pageindex_path = write_pageindex(page_index, pageindex_dir)
    print(f"PageIndex written: {pageindex_path}")
    vector_store_ingest_ldus(ldus, path=vector_store_dir)
    print(f"Vector store: ingested {len(ldus)} LDUs into {vector_store_dir}")
    init_fact_table(fact_table_path)
    facts = extract_facts_from_ldus(ldus, path=fact_table_path, enabled=True, table_only=False)
    print(f"FactTable: inserted {facts} fact(s) into {fact_table_path}")

    # ---------- Step 4: Query with Provenance ----------
    print("\n=== Step 4: Query with Provenance ===")
    question = (args.question or "").strip()
    if not question:
        question = input("Ask a natural-language question about the document: ").strip()
    if not question:
        question = "What is this document about?"
    resolver = lambda doc_id: _document_name_resolver_from_file(base, doc_id)
    result = query(
        question,
        document_id=profile.document_id,
        vector_store_path=vector_store_dir,
        fact_table_path=fact_table_path,
        pageindex_dir=pageindex_dir,
        document_name_resolver=resolver,
    )
    print("\n--- Answer ---")
    print(result["answer"])
    print("\n--- ProvenanceChain (verified: {}) ---".format(result["verified"]))
    chain = result.get("provenance_chain") or {}
    items = chain.get("items") or []
    for i, cit in enumerate(items, 1):
        name = cit.get("document_name", "")
        page = cit.get("page_number", "")
        bbox = cit.get("bbox") or {}
        bbox_str = (
            f"bbox=[{bbox.get('x0')},{bbox.get('y0')},{bbox.get('x1')},{bbox.get('y1')}]"
            if bbox
            else "bbox=N/A"
        )
        h = (cit.get("content_hash") or "")[:12]
        print(f"  {i}. document_name={name} page_number={page} {bbox_str} content_hash={h}...")
    if not items:
        print("  (no citations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
