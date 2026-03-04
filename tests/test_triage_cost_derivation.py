# Unit tests for estimated_extraction_cost derivation (P1-T006). Invariants from origin_type + layout_complexity.

import pytest
from src.agents.triage import derive_estimated_extraction_cost
from src.models import LayoutComplexity, OriginType, EstimatedExtractionCost


def test_scanned_image_always_needs_vision_model():
    """origin_type=scanned_image → estimated_extraction_cost is always needs_vision_model."""
    cost = derive_estimated_extraction_cost(OriginType.SCANNED_IMAGE, LayoutComplexity.SINGLE_COLUMN)
    assert cost == EstimatedExtractionCost.NEEDS_VISION_MODEL
    cost = derive_estimated_extraction_cost(OriginType.SCANNED_IMAGE, LayoutComplexity.TABLE_HEAVY)
    assert cost == EstimatedExtractionCost.NEEDS_VISION_MODEL


def test_table_heavy_multi_column_never_fast_text_sufficient():
    """layout_complexity in (table_heavy, multi_column) → needs_layout_model or needs_vision_model, never fast_text_sufficient."""
    for layout in (LayoutComplexity.TABLE_HEAVY, LayoutComplexity.MULTI_COLUMN):
        cost = derive_estimated_extraction_cost(OriginType.NATIVE_DIGITAL, layout)
        assert cost != EstimatedExtractionCost.FAST_TEXT_SUFFICIENT
        assert cost in (EstimatedExtractionCost.NEEDS_LAYOUT_MODEL, EstimatedExtractionCost.NEEDS_VISION_MODEL)


def test_native_digital_single_column_fast_text_sufficient():
    """origin_type=native_digital and layout_complexity=single_column → fast_text_sufficient."""
    cost = derive_estimated_extraction_cost(OriginType.NATIVE_DIGITAL, LayoutComplexity.SINGLE_COLUMN)
    assert cost == EstimatedExtractionCost.FAST_TEXT_SUFFICIENT
