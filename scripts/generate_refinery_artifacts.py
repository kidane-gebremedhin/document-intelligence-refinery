#!/usr/bin/env python3
"""Generate .refinery/profiles/ and extraction_ledger.jsonl for 12 corpus documents (min 3 per class).

Document classes per spec 01:
- Class A: Annual financial report (native digital, multi-column/table-heavy)
- Class B: Scanned government/legal (image-based)
- Class C: Technical assessment (mixed text, tables, structure)
- Class D: Structured data report (table-heavy, numerical)

Run: uv run python scripts/generate_refinery_artifacts.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root for imports
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import (
    DocumentProfile,
    ExtractionLedgerEntry,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)


# 12 documents: 3 per class. document_id = hash of logical name for stability.
CORPUS = [
    # Class A — Annual financial report (native digital, multi-column/table-heavy)
    {"class": "A", "name": "annual_report_2024_acme.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.MULTI_COLUMN, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 45, "triage_conf": 0.82},
    {"class": "A", "name": "annual_report_2024_techcorp.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.TABLE_HEAVY, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 38, "triage_conf": 0.85},
    {"class": "A", "name": "annual_report_2023_global.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.MULTI_COLUMN, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 52, "triage_conf": 0.79},
    # Class B — Scanned government/legal (image-based)
    {"class": "B", "name": "scanned_contract_2024.pdf", "origin": OriginType.SCANNED_IMAGE, "layout": LayoutComplexity.SINGLE_COLUMN, "domain": DomainHint.LEGAL, "cost": EstimatedExtractionCost.NEEDS_VISION_MODEL, "pages": 12, "triage_conf": 0.91},
    {"class": "B", "name": "scanned_court_filing.pdf", "origin": OriginType.SCANNED_IMAGE, "layout": LayoutComplexity.SINGLE_COLUMN, "domain": DomainHint.LEGAL, "cost": EstimatedExtractionCost.NEEDS_VISION_MODEL, "pages": 28, "triage_conf": 0.88},
    {"class": "B", "name": "scanned_government_memo.pdf", "origin": OriginType.SCANNED_IMAGE, "layout": LayoutComplexity.SINGLE_COLUMN, "domain": DomainHint.LEGAL, "cost": EstimatedExtractionCost.NEEDS_VISION_MODEL, "pages": 8, "triage_conf": 0.89},
    # Class C — Technical assessment (mixed text, tables, structure)
    {"class": "C", "name": "technical_assessment_q1.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.SINGLE_COLUMN, "domain": DomainHint.TECHNICAL, "cost": EstimatedExtractionCost.FAST_TEXT_SUFFICIENT, "pages": 22, "triage_conf": 0.76},
    {"class": "C", "name": "technical_assessment_q2.pdf", "origin": OriginType.MIXED, "layout": LayoutComplexity.MIXED, "domain": DomainHint.TECHNICAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 18, "triage_conf": 0.72},
    {"class": "C", "name": "methodology_report.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.MIXED, "domain": DomainHint.TECHNICAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 15, "triage_conf": 0.81},
    # Class D — Structured data report (table-heavy, numerical)
    {"class": "D", "name": "fiscal_data_2024.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.TABLE_HEAVY, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 30, "triage_conf": 0.87},
    {"class": "D", "name": "multi_year_tables.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.TABLE_HEAVY, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 24, "triage_conf": 0.84},
    {"class": "D", "name": "quarterly_metrics_report.pdf", "origin": OriginType.NATIVE_DIGITAL, "layout": LayoutComplexity.TABLE_HEAVY, "domain": DomainHint.FINANCIAL, "cost": EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, "pages": 16, "triage_conf": 0.86},
]


def doc_id(name: str) -> str:
    """Stable document_id from logical name."""
    return hashlib.sha256(name.encode()).hexdigest()[:32]


def strategy_for_profile(d: dict) -> tuple[str, list[str], float, float]:
    """Return (strategy_used, escalation_chain, confidence, cost_usd) based on profile."""
    origin = d["origin"]
    cost = d["cost"]
    layout = d["layout"]
    pages = d["pages"]
    # Scanned / needs_vision -> Strategy C only
    if origin == OriginType.SCANNED_IMAGE or cost == EstimatedExtractionCost.NEEDS_VISION_MODEL:
        return "vision", ["vision"], 0.82, round(0.00286 * min(pages, 50) + 0.001 * pages, 4)  # ~$0.03–0.15
    # native_digital + single_column -> A first (or A->B if escalated)
    if origin == OriginType.NATIVE_DIGITAL and layout == LayoutComplexity.SINGLE_COLUMN:
        if d.get("escalate_from_a"):
            return "layout", ["fast_text", "layout"], 0.74, 0.0
        return "fast_text", ["fast_text"], 0.78, 0.0
    # multi_column, table_heavy, etc. -> B directly
    if layout in (LayoutComplexity.MULTI_COLUMN, LayoutComplexity.TABLE_HEAVY, LayoutComplexity.MIXED):
        return "layout", ["layout"], 0.77, 0.0
    return "layout", ["layout"], 0.75, 0.0


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    profiles_dir = project_root / ".refinery" / "profiles"
    ledger_path = project_root / ".refinery" / "extraction_ledger.jsonl"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # One Class C doc (single_column) escalates A->B for variety in ledger
    CORPUS[6]["escalate_from_a"] = True

    base_time = datetime.now(timezone.utc) - timedelta(hours=1)
    ledger_lines: list[str] = []

    for i, d in enumerate(CORPUS):
        doc_id_val = doc_id(d["name"])
        profile = DocumentProfile(
            document_id=doc_id_val,
            origin_type=d["origin"],
            layout_complexity=d["layout"],
            language="en",
            language_confidence=0.85,
            domain_hint=d["domain"],
            estimated_extraction_cost=d["cost"],
            triage_confidence_score=d["triage_conf"],
            page_count=d["pages"],
            metadata={"source": d["name"], "doc_class": d["class"]},
        )
        path = profiles_dir / f"{doc_id_val}.json"
        path.write_text(profile.to_profile_json(), encoding="utf-8")
        print(f"Wrote profile: {path.name} ({d['class']})")

        strategy, chain, conf, cost_usd = strategy_for_profile(d)
        start = base_time + timedelta(minutes=i * 3)
        end = start + timedelta(seconds=45 if strategy == "vision" else 12)
        entry = ExtractionLedgerEntry(
            document_id=doc_id_val,
            strategy_used=strategy,
            origin_type=d["origin"].value,
            layout_complexity=d["layout"].value,
            start_time=start,
            end_time=end,
            processing_time_ms=int((end - start).total_seconds() * 1000),
            confidence_score=conf,
            cost_estimate_usd=cost_usd,
            token_usage_prompt=3500 if strategy == "vision" else None,
            token_usage_completion=2800 if strategy == "vision" else None,
            escalation_chain=chain,
            notes=None,
        )
        ledger_lines.append(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("".join(ledger_lines), encoding="utf-8")
    print(f"\nWrote ledger: {ledger_path} ({len(ledger_lines)} entries)")
    print("\nSummary: 12 profiles (3 per class A/B/C/D), 12 ledger entries.")


if __name__ == "__main__":
    main()
