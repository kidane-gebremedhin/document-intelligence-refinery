# Unit tests for DocumentProfile (spec 07 §3). Task: P1-T002.

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models import (
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)


def _valid_base() -> dict:
    """Minimal valid payload: native_digital + single_column → fast_text_sufficient."""
    return {
        "document_id": "doc-001",
        "origin_type": OriginType.NATIVE_DIGITAL,
        "layout_complexity": LayoutComplexity.SINGLE_COLUMN,
        "language": "en",
        "language_confidence": 0.95,
        "domain_hint": DomainHint.GENERAL,
        "estimated_extraction_cost": EstimatedExtractionCost.FAST_TEXT_SUFFICIENT,
        "triage_confidence_score": 0.9,
        "page_count": 10,
    }


# -----------------------------------------------------------------------------
# Required fields and valid instantiation
# -----------------------------------------------------------------------------


def test_document_profile_valid_native_digital_single_column():
    """Valid dict for native_digital + single_column yields estimated_extraction_cost == fast_text_sufficient."""
    data = _valid_base()
    profile = DocumentProfile(**data)
    assert profile.estimated_extraction_cost == EstimatedExtractionCost.FAST_TEXT_SUFFICIENT
    assert profile.origin_type == OriginType.NATIVE_DIGITAL
    assert profile.layout_complexity == LayoutComplexity.SINGLE_COLUMN
    assert profile.document_id == "doc-001"
    assert profile.page_count == 10


def test_document_profile_required_fields_rejected():
    """Missing required fields raise ValidationError."""
    data = _valid_base()
    del data["document_id"]
    with pytest.raises(ValidationError):
        DocumentProfile(**data)

    data = _valid_base()
    del data["page_count"]
    with pytest.raises(ValidationError):
        DocumentProfile(**data)


# -----------------------------------------------------------------------------
# Confidence range (0..1)
# -----------------------------------------------------------------------------


def test_language_confidence_in_range():
    """language_confidence must be in [0, 1]."""
    data = _valid_base()
    data["language_confidence"] = 0.5
    profile = DocumentProfile(**data)
    assert profile.language_confidence == 0.5

    data["language_confidence"] = 1.0
    profile = DocumentProfile(**data)
    assert profile.language_confidence == 1.0


def test_language_confidence_out_of_range_rejected():
    """language_confidence outside [0, 1] raises."""
    data = _valid_base()
    data["language_confidence"] = 1.1
    with pytest.raises(ValidationError):
        DocumentProfile(**data)
    data["language_confidence"] = -0.1
    with pytest.raises(ValidationError):
        DocumentProfile(**data)


def test_triage_confidence_score_in_range():
    """triage_confidence_score must be in [0, 1]."""
    data = _valid_base()
    data["triage_confidence_score"] = 0.0
    profile = DocumentProfile(**data)
    assert profile.triage_confidence_score == 0.0


def test_triage_confidence_score_out_of_range_rejected():
    """triage_confidence_score outside [0, 1] raises."""
    data = _valid_base()
    data["triage_confidence_score"] = 1.5
    with pytest.raises(ValidationError):
        DocumentProfile(**data)


# -----------------------------------------------------------------------------
# Triage rule validators (P1-T002 acceptance)
# -----------------------------------------------------------------------------


def test_scanned_image_requires_needs_vision_model():
    """origin_type=scanned_image with estimated_extraction_cost=needs_layout_model raises."""
    data = _valid_base()
    data["origin_type"] = OriginType.SCANNED_IMAGE
    data["estimated_extraction_cost"] = EstimatedExtractionCost.NEEDS_LAYOUT_MODEL
    with pytest.raises(ValidationError) as exc_info:
        DocumentProfile(**data)
    assert "scanned_image" in str(exc_info.value).lower() or "vision" in str(exc_info.value).lower()


def test_scanned_image_accepts_needs_vision_model():
    """origin_type=scanned_image with estimated_extraction_cost=needs_vision_model is valid."""
    data = _valid_base()
    data["origin_type"] = OriginType.SCANNED_IMAGE
    data["estimated_extraction_cost"] = EstimatedExtractionCost.NEEDS_VISION_MODEL
    data["layout_complexity"] = LayoutComplexity.MIXED
    profile = DocumentProfile(**data)
    assert profile.estimated_extraction_cost == EstimatedExtractionCost.NEEDS_VISION_MODEL


def test_table_heavy_rejects_fast_text_sufficient():
    """layout_complexity=table_heavy with estimated_extraction_cost=fast_text_sufficient raises."""
    data = _valid_base()
    data["layout_complexity"] = LayoutComplexity.TABLE_HEAVY
    data["estimated_extraction_cost"] = EstimatedExtractionCost.FAST_TEXT_SUFFICIENT
    with pytest.raises(ValidationError) as exc_info:
        DocumentProfile(**data)
    assert "table_heavy" in str(exc_info.value).lower() or "layout" in str(exc_info.value).lower()


def test_page_count_ge_one():
    """page_count must be >= 1."""
    data = _valid_base()
    data["page_count"] = 0
    with pytest.raises(ValidationError):
        DocumentProfile(**data)


# -----------------------------------------------------------------------------
# Enum constraints
# -----------------------------------------------------------------------------


def test_invalid_origin_type_rejected():
    """Invalid origin_type string raises."""
    data = _valid_base()
    data["origin_type"] = "invalid_origin"
    with pytest.raises(ValidationError):
        DocumentProfile(**data)


def test_domain_hint_enum():
    """domain_hint accepts all enum values."""
    data = _valid_base()
    for hint in DomainHint:
        data["domain_hint"] = hint
        profile = DocumentProfile(**data)
        assert profile.domain_hint == hint


# -----------------------------------------------------------------------------
# JSON serialization round-trip and profile JSON
# -----------------------------------------------------------------------------


def test_json_round_trip():
    """Serialization to JSON round-trips (load dict, build profile, dump, load, build again)."""
    data = _valid_base()
    data["created_at"] = datetime.now(timezone.utc)
    profile = DocumentProfile(**data)
    raw = profile.model_dump(mode="json")
    profile2 = DocumentProfile(**raw)
    assert profile2.document_id == profile.document_id
    assert profile2.estimated_extraction_cost == profile.estimated_extraction_cost


def test_to_profile_json_deterministic_and_friendly():
    """to_profile_json() produces valid JSON suitable for .refinery/profiles/{doc_id}.json."""
    data = _valid_base()
    profile = DocumentProfile(**data)
    s = profile.to_profile_json()
    parsed = json.loads(s)
    assert parsed["document_id"] == "doc-001"
    assert parsed["origin_type"] == "native_digital"
    assert parsed["estimated_extraction_cost"] == "fast_text_sufficient"
    assert "created_at" in parsed
    # Optional fields excluded when None
    profile_with_notes = DocumentProfile(**{**_valid_base(), "notes": "test"})
    s2 = profile_with_notes.to_profile_json(exclude_none=True)
    parsed2 = json.loads(s2)
    assert parsed2["notes"] == "test"
