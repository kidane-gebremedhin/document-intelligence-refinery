# Unit tests for audit mode. Spec 06 §7–8; plan §5.

from pathlib import Path

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    ProvenanceItem,
    compute_content_hash,
)
from src.data.vector_store import ingest_ldus
from src.agents.audit import (
    AuditResult,
    UNVERIFIABLE_MESSAGE,
    audit,
    audit_claim,
)


def _provenance_item(
    document_id: str = "doc1",
    document_name: str = "Report.pdf",
    page_number: int = 42,
    content_hash: str = "abc123",
    snippet: str = "Revenue was $4.2B in Q3 2024.",
) -> ProvenanceItem:
    return ProvenanceItem(
        document_id=document_id,
        document_name=document_name,
        page_number=page_number,
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0),
        content_hash=content_hash,
        snippet=snippet,
    )


def test_audit_claim_evidence_found_returns_verified():
    """When search returns evidence, audit returns verified=True and non-empty chain."""
    evidence = [_provenance_item(snippet="Revenue $4.2B Q3 2024.")]

    def search(_claim: str, doc_id: str | None) -> list[ProvenanceItem]:
        return evidence

    result = audit_claim("Revenue was $4.2B in Q3 2024.", search)

    assert isinstance(result, AuditResult)
    assert result.verified is True
    assert result.status == "verified"
    assert result.chain.verified is True
    assert len(result.chain.items) == 1
    assert result.chain.items[0].snippet == "Revenue $4.2B Q3 2024."
    assert "supported" in result.response_text.lower()


def test_audit_claim_no_evidence_returns_unverifiable():
    """When search returns no evidence, audit returns verified=False and explicit unverifiable."""
    def search(_claim: str, doc_id: str | None) -> list[ProvenanceItem]:
        return []

    result = audit_claim("Revenue was $99.9B in Q1 2099.", search)

    assert result.verified is False
    assert result.status == "unverifiable"
    assert result.chain.verified is False
    assert result.chain.items == []
    assert "could not be verified" in result.response_text.lower() or "unverifiable" in result.response_text.lower()
    assert result.response_text == UNVERIFIABLE_MESSAGE


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


def _ldu(id_: str, document_id: str, text: str, page: int = 1) -> LDU:
    return LDU(
        id=id_,
        document_id=document_id,
        content_type=LDUContentType.PARAGRAPH,
        text=text,
        page_refs=[PageRef(document_id=document_id, page_number=page)],
        bounding_boxes=[_bbox()],
        token_count=2,
        content_hash=compute_content_hash("paragraph", text),
    )


def test_audit_not_found_empty_corpus(tmp_path: Path) -> None:
    """Empty corpus or non-matching claim → unverifiable, empty citations, no exception."""
    vector_path = tmp_path / "vs"
    vector_path.mkdir(parents=True, exist_ok=True)
    fact_path = tmp_path / "facts.db"
    result = audit(
        "The report states revenue was $99.9B in Q1 2099.",
        document_id="doc_none",
        vector_store_path=vector_path,
        fact_table_path=fact_path,
    )
    assert result.verified is False
    assert result.status == "unverifiable"
    assert result.chain.verified is False
    assert len(result.chain.items) == 0
    assert "could not be verified" in result.response_text.lower() or "unverifiable" in result.response_text.lower()


def test_audit_found_from_vector_store(tmp_path: Path) -> None:
    """Claim supported by ingested LDU → verified, ProvenanceChain has ≥1 citation with doc name, page, bbox, content_hash."""
    ldus = [
        _ldu("ldu_1", "doc1", "Revenue for Q3 was four point two billion dollars.", page=1),
        _ldu("ldu_2", "doc1", "Risk factors include market volatility.", page=2),
        _ldu("ldu_3", "doc1", "The auditor issued an unqualified opinion.", page=3),
    ]
    vector_path = tmp_path / "vs"
    ingest_ldus(ldus, path=vector_path)
    fact_path = tmp_path / "facts.db"

    result = audit(
        "revenue quarterly four point two billion",
        document_id="doc1",
        vector_store_path=vector_path,
        fact_table_path=fact_path,
        document_name_resolver=lambda doc_id: "Report.pdf" if doc_id == "doc1" else doc_id,
    )

    assert result.verified is True
    assert result.status == "verified"
    assert result.chain.verified is True
    assert len(result.chain.items) >= 1
    hit = result.chain.items[0]
    assert hit.document_id == "doc1"
    assert hit.document_name == "Report.pdf"
    assert hit.page_number >= 1
    assert hit.bbox is not None
    assert hit.content_hash != ""
    assert "supported" in result.response_text.lower()
