# Unit tests for ProvenanceItem, ProvenanceChain, and attach helper. Task: P4 provenance.

import pytest
from pydantic import ValidationError

from src.models import (
    BoundingBox,
    ProvenanceChain,
    ProvenanceItem,
    attach_provenance_to_answer,
    build_provenance_chain,
)


def _item(
    document_id: str = "doc1",
    document_name: str = "Report.pdf",
    page_number: int = 1,
    content_hash: str = "abc123",
    snippet: str = "Revenue was $4.2B.",
) -> ProvenanceItem:
    return ProvenanceItem(
        document_id=document_id,
        document_name=document_name,
        page_number=page_number,
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0),
        content_hash=content_hash,
        snippet=snippet,
    )


# -----------------------------------------------------------------------------
# ProvenanceItem — required fields
# -----------------------------------------------------------------------------


def test_provenance_item_has_required_fields():
    """ProvenanceItem includes page_number, bbox, content_hash, snippet."""
    item = _item(snippet="Excerpt here.")
    assert item.page_number == 1
    assert item.bbox.x1 == 100.0
    assert item.content_hash == "abc123"
    assert item.snippet == "Excerpt here."


def test_provenance_item_optional_ldu_table_figure():
    """ProvenanceItem may set ldu_id, table_id, figure_id."""
    item = ProvenanceItem(
        document_id="doc1",
        document_name="Doc.pdf",
        page_number=2,
        bbox=BoundingBox(x0=10, y0=20, x1=90, y1=80),
        content_hash="h1",
        snippet="Table 3",
        ldu_id="ldu_42",
        table_id="table_3",
    )
    assert item.ldu_id == "ldu_42"
    assert item.table_id == "table_3"
    assert item.figure_id is None


# -----------------------------------------------------------------------------
# ProvenanceChain — verified invariant
# -----------------------------------------------------------------------------


def test_provenance_chain_verified_true_requires_non_empty_items():
    """When verified=True, items must be non-empty; validator rejects empty."""
    with pytest.raises(ValidationError) as exc_info:
        ProvenanceChain(answer_id="a1", items=[], verified=True)
    assert "verified" in str(exc_info.value).lower() or "non-empty" in str(exc_info.value).lower() or "items" in str(exc_info.value).lower()


def test_provenance_chain_verified_true_with_items_passes():
    """When verified=True and items non-empty, validation passes."""
    items = [_item()]
    chain = ProvenanceChain(answer_id="a1", items=items, verified=True)
    assert chain.verified is True
    assert len(chain.items) == 1


def test_provenance_chain_verified_false_allows_empty_items():
    """When verified=False, items may be empty (unverifiable claim)."""
    chain = ProvenanceChain(answer_id="a1", items=[], verified=False)
    assert chain.verified is False
    assert chain.items == []


def test_provenance_chain_verified_false_with_items_passes():
    """verified=False with non-empty items is valid."""
    chain = ProvenanceChain(answer_id="a1", items=[_item()], verified=False)
    assert chain.items


# -----------------------------------------------------------------------------
# Helper: attach_provenance_to_answer
# -----------------------------------------------------------------------------


def test_attach_provenance_to_answer_returns_tuple_and_chain():
    """attach_provenance_to_answer returns (answer_text, ProvenanceChain)."""
    answer = "Revenue was $4.2B in Q3 2024."
    items = [_item(snippet="Revenue $4.2B")]
    text, chain = attach_provenance_to_answer(answer, items, answer_id="ans_1")
    assert text == answer
    assert isinstance(chain, ProvenanceChain)
    assert chain.answer_id == "ans_1"
    assert len(chain.items) == 1
    assert chain.verified is True


def test_attach_provenance_to_answer_verified_none_implies_from_items():
    """When verified=None, verified is True if items non-empty, else False."""
    _, chain_full = attach_provenance_to_answer("Yes.", [_item()], verified=None)
    assert chain_full.verified is True
    _, chain_empty = attach_provenance_to_answer("Unknown.", [], verified=None)
    assert chain_empty.verified is False


def test_attach_provenance_to_answer_verified_true_empty_items_raises():
    """When verified=True and items empty, build_provenance_chain would raise; attach uses chain construction."""
    with pytest.raises(ValidationError):
        attach_provenance_to_answer("Claim.", [], answer_id="a1", verified=True)


# -----------------------------------------------------------------------------
# build_provenance_chain
# -----------------------------------------------------------------------------


def test_build_provenance_chain_verified_invariant():
    """build_provenance_chain enforces verified invariant."""
    chain = build_provenance_chain("id1", [_item()], verified=True)
    assert chain.verified and len(chain.items) == 1
    with pytest.raises(ValidationError):
        build_provenance_chain("id2", [], verified=True)
