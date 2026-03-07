# Unit tests for vector store: ingest LDUs and query. P4-T002.

from pathlib import Path

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.data.vector_store import ingest_ldus, search, DEFAULT_VECTOR_STORE_PATH


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


def test_ingest_three_ldus_and_retrieve_one_by_query(tmp_path: Path) -> None:
    ldus = [
        _ldu("ldu_1", "doc1", "Revenue for Q3 was four point two billion dollars.", page=1),
        _ldu("ldu_2", "doc1", "Risk factors include market volatility and regulation.", page=2),
        _ldu("ldu_3", "doc1", "The auditor issued an unqualified opinion.", page=3),
    ]
    path = tmp_path / "vector_store"
    n = ingest_ldus(ldus, path=path)
    assert n == 3

    results = search("revenue and quarterly results", top_k=1, path=path)
    assert len(results) >= 1
    hit = results[0]
    assert "content" in hit
    assert "document_id" in hit
    assert "ldu_id" in hit
    assert "page_refs" in hit
    assert "bounding_boxes" in hit
    assert "content_hash" in hit
    assert hit["document_id"] == "doc1"
    assert hit["ldu_id"] in ("ldu_1", "ldu_2", "ldu_3")
    assert isinstance(hit["page_refs"], list)
    assert isinstance(hit["bounding_boxes"], list)
    assert hit["content_hash"] != ""

    results_3 = search("auditor opinion", top_k=3, path=path)
    assert len(results_3) <= 3
    ldu_ids = [r["ldu_id"] for r in results_3]
    assert "ldu_3" in ldu_ids or any("auditor" in (r.get("content") or "").lower() for r in results_3)


def test_search_empty_store_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty_store"
    path.mkdir(parents=True, exist_ok=True)
    results = search("anything", top_k=5, path=path)
    assert results == []


def test_ingest_empty_list_returns_zero(tmp_path: Path) -> None:
    n = ingest_ldus([], path=tmp_path / "vs")
    assert n == 0


def test_search_with_document_id_filter(tmp_path: Path) -> None:
    ldus = [
        _ldu("a1", "doc_a", "Document A content."),
        _ldu("b1", "doc_b", "Document B content."),
    ]
    ingest_ldus(ldus, path=tmp_path / "vs")
    results = search("document content", top_k=5, path=tmp_path / "vs", document_ids=["doc_a"])
    assert all(r["document_id"] == "doc_a" for r in results)
