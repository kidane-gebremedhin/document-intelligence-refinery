# Unit tests for audit mode. Spec 06 §7–8; plan §5.

import pytest

from src.models import BoundingBox, ProvenanceItem
from src.agents.audit import (
    AuditResult,
    UNVERIFIABLE_MESSAGE,
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
