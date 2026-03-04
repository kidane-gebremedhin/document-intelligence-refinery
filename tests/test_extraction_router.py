# Unit tests for ExtractionRouter. Task: P2-T007 / P2-T010.

from pathlib import Path

import pytest

from src.models import (
    BoundingBox,
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    ExtractedDocument,
    LayoutComplexity,
    OriginType,
    TextBlock,
)
from src.strategies import BaseExtractor, ExtractionResult
from src.agents import ExtractionRouter


def _minimal_document(document_id: str, strategy: str = "layout") -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id,
        pages=1,
        strategy_used=strategy,
        strategy_confidence=0.85,
        text_blocks=[
            TextBlock(
                id="b1",
                document_id=document_id,
                page_number=1,
                bbox=BoundingBox(x0=0, y0=0, x1=100, y1=20),
                text="Extracted by layout",
                reading_order_index=0,
            )
        ],
    )


class DummyLowConfidenceA(BaseExtractor):
    """Strategy A that always returns low confidence (escalate)."""

    def extract(self, doc_path: Path | str, profile: DocumentProfile) -> ExtractionResult:
        return ExtractionResult(
            extracted_document=None,
            confidence_score=0.3,
            cost_estimate_usd=0.0,
            strategy_name="fast_text",
            notes="confidence_below_threshold",
        )


class DummySuccessB(BaseExtractor):
    """Strategy B that always returns a valid document with high confidence."""

    def extract(self, doc_path: Path | str, profile: DocumentProfile) -> ExtractionResult:
        doc = _minimal_document(profile.document_id, strategy="layout")
        return ExtractionResult(
            extracted_document=doc,
            confidence_score=0.85,
            cost_estimate_usd=0.0,
            strategy_name="layout",
        )


class DummyStubC(BaseExtractor):
    """Strategy C stub that never returns a document."""

    def extract(self, doc_path: Path | str, profile: DocumentProfile) -> ExtractionResult:
        return ExtractionResult(
            extracted_document=None,
            confidence_score=0.0,
            cost_estimate_usd=0.0,
            strategy_name="vision",
            notes="stub",
        )


def _profile_for_a_then_b() -> DocumentProfile:
    """Profile that permits Strategy A first (native_digital, single_column)."""
    return DocumentProfile(
        document_id="doc-escalate",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )


def test_router_escalates_a_to_b_and_emits_b_result(tmp_path: Path):
    """
    When A returns low confidence, router must not emit A output;
    it escalates to B and emits B's ExtractedDocument. Ledger has
    escalation_chain [fast_text, layout] and strategy_used layout.
    """
    ledger_file = tmp_path / "ledger.jsonl"
    router = ExtractionRouter(
        fast_text_extractor=DummyLowConfidenceA(),
        layout_extractor=DummySuccessB(),
        vision_extractor=DummyStubC(),
        ledger_path=ledger_file,
    )
    profile = _profile_for_a_then_b()

    doc, result = router.extract(Path("/any/doc.pdf"), profile)

    assert doc is not None
    assert doc.document_id == "doc-escalate"
    assert doc.strategy_used == "layout"
    assert result.success is True
    assert result.strategy_name == "layout"
    assert result.extracted_document is doc

    assert ledger_file.exists()
    lines = ledger_file.read_text().strip().split("\n")
    assert len(lines) == 1
    import json
    entry = json.loads(lines[0])
    assert entry["document_id"] == "doc-escalate"
    assert entry["strategy_used"] == "layout"
    assert entry["escalation_chain"] == ["fast_text", "layout"]
    assert entry["confidence_score"] == 0.85
    assert "confidence_below_threshold" in (entry.get("notes") or "")


def test_router_does_not_emit_a_output_when_a_escalates(tmp_path: Path):
    """Emitted document must be from B (layout), not A (fast_text)."""
    ledger_file = tmp_path / "ledger2.jsonl"
    router = ExtractionRouter(
        fast_text_extractor=DummyLowConfidenceA(),
        layout_extractor=DummySuccessB(),
        vision_extractor=DummyStubC(),
        ledger_path=ledger_file,
    )
    profile = _profile_for_a_then_b()

    doc, _ = router.extract(Path("/any/doc.pdf"), profile)

    assert doc.strategy_used == "layout"
    assert doc.text_blocks[0].text == "Extracted by layout"


def test_router_all_strategies_fail_emits_escalation_failed(tmp_path: Path):
    """When A and B both fail (e.g. B also low confidence), ledger has strategy_used escalation_failed."""

    class DummyFailB(BaseExtractor):
        def extract(self, doc_path: Path | str, profile: DocumentProfile) -> ExtractionResult:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.2,
                cost_estimate_usd=0.0,
                strategy_name="layout",
                notes="error",
            )

    ledger_file = tmp_path / "ledger3.jsonl"
    router = ExtractionRouter(
        fast_text_extractor=DummyLowConfidenceA(),
        layout_extractor=DummyFailB(),
        vision_extractor=DummyStubC(),
        ledger_path=ledger_file,
    )
    profile = _profile_for_a_then_b()

    doc, result = router.extract(Path("/any/doc.pdf"), profile)

    assert doc is None
    assert result.success is False

    lines = ledger_file.read_text().strip().split("\n")
    assert len(lines) == 1
    import json
    entry = json.loads(lines[0])
    assert entry["strategy_used"] == "escalation_failed"
    assert entry["escalation_chain"] == ["fast_text", "layout", "vision"]
