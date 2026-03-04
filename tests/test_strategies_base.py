# Unit tests for BaseExtractor interface and ExtractionResult. Task: P2-T002.

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


def test_extraction_result_success():
    """ExtractionResult with document is success; confidence and strategy_name set."""
    doc = ExtractedDocument(
        document_id="doc1",
        pages=1,
        strategy_used="fast_text",
        strategy_confidence=0.9,
        text_blocks=[
            TextBlock(
                id="b1",
                document_id="doc1",
                page_number=1,
                bbox=BoundingBox(x0=0, y0=0, x1=100, y1=20),
                text="Hello",
                reading_order_index=0,
            )
        ],
    )
    result = ExtractionResult(
        extracted_document=doc,
        confidence_score=0.9,
        cost_estimate_usd=0.0,
        strategy_name="fast_text",
        notes=None,
    )
    assert result.success is True
    assert result.extracted_document is doc
    assert result.confidence_score == 0.9
    assert result.strategy_name == "fast_text"
    assert result.cost_estimate_usd == 0.0


def test_extraction_result_escalation():
    """ExtractionResult with no document represents escalation/failure."""
    result = ExtractionResult(
        extracted_document=None,
        confidence_score=0.3,
        cost_estimate_usd=0.0,
        strategy_name="fast_text",
        notes="confidence_below_threshold",
    )
    assert result.success is False
    assert result.extracted_document is None
    assert result.notes == "confidence_below_threshold"


def test_dummy_extractor_implements_protocol():
    """A dummy extractor implementing BaseExtractor can be used as an extractor."""

    class DummyExtractor:
        """Stub that always returns escalation (no document)."""

        def extract(
            self,
            doc_path: Path | str,
            profile: DocumentProfile,
        ) -> ExtractionResult:
            return ExtractionResult(
                extracted_document=None,
                confidence_score=0.0,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
                notes="stub",
            )

    extractor: BaseExtractor = DummyExtractor()
    profile = DocumentProfile(
        document_id="doc1",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )
    result = extractor.extract("/nonexistent.pdf", profile)
    assert isinstance(result, ExtractionResult)
    assert result.success is False
    assert result.strategy_name == "fast_text"
    assert result.notes == "stub"


def test_dummy_extractor_success():
    """A dummy extractor can return a success result with minimal ExtractedDocument."""

    class StubSuccessExtractor:
        def extract(
            self,
            doc_path: Path | str,
            profile: DocumentProfile,
        ) -> ExtractionResult:
            doc = ExtractedDocument(
                document_id=profile.document_id,
                pages=1,
                strategy_used="fast_text",
                strategy_confidence=0.85,
                text_blocks=[
                    TextBlock(
                        id="b1",
                        document_id=profile.document_id,
                        page_number=1,
                        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=20),
                        text="Stub text",
                        reading_order_index=0,
                    )
                ],
            )
            return ExtractionResult(
                extracted_document=doc,
                confidence_score=0.85,
                cost_estimate_usd=0.0,
                strategy_name="fast_text",
            )

    extractor: BaseExtractor = StubSuccessExtractor()
    profile = DocumentProfile(
        document_id="doc99",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        language="en",
        language_confidence=0.9,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        triage_confidence_score=0.95,
        page_count=1,
    )
    result = extractor.extract(Path("/any/path.pdf"), profile)
    assert result.success is True
    assert result.extracted_document is not None
    assert result.extracted_document.document_id == "doc99"
    assert result.confidence_score == 0.85
    assert result.strategy_name == "fast_text"
