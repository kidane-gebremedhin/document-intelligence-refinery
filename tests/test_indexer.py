# Unit tests for PageIndex builder and pageindex_query. P3-T004–T007.

import json
from pathlib import Path

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.agents.indexer import (
    build_page_index,
    load_pageindex,
    pageindex_query,
    write_pageindex,
    StubSummarizer,
    CachedSummarizer,
    DEFAULT_PAGEINDEX_DIR,
)


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0.0, y0=0.0, x1=100.0, y1=20.0)


def _ldu(
    id_: str,
    doc_id: str,
    content_type: LDUContentType,
    text: str,
    page: int = 1,
) -> LDU:
    return LDU(
        id=id_,
        document_id=doc_id,
        content_type=content_type,
        text=text,
        page_refs=[PageRef(document_id=doc_id, page_number=page)],
        bounding_boxes=[_bbox()],
        token_count=2,
        content_hash=compute_content_hash(content_type.value, text),
    )


def test_build_page_index_empty_ldus():
    pi = build_page_index([], "doc1", 5)
    assert pi.document_id == "doc1"
    assert pi.page_count == 5
    assert pi.root.id == "root"
    assert pi.root.page_start == 1 and pi.root.page_end == 5
    assert pi.root.child_sections == []
    assert pi.root.ldu_ids == []


def test_build_page_index_root_only_when_no_headings():
    ldus = [
        _ldu("l1", "doc1", LDUContentType.PARAGRAPH, "Hello"),
        _ldu("l2", "doc1", LDUContentType.PARAGRAPH, "World"),
    ]
    pi = build_page_index(ldus, "doc1", 3)
    assert pi.root.title == "Document"
    assert pi.root.ldu_ids == ["l1", "l2"]
    assert pi.root.data_types_present == ["paragraphs"]
    assert pi.root.child_sections == []


def test_build_page_index_sections_from_headings():
    ldus = [
        _ldu("l1", "doc1", LDUContentType.SECTION_INTRO, "1. Intro", page=1),
        _ldu("l2", "doc1", LDUContentType.PARAGRAPH, "Text.", page=1),
        _ldu("l3", "doc1", LDUContentType.SECTION_HEADER, "2. Risks", page=2),
        _ldu("l4", "doc1", LDUContentType.PARAGRAPH, "Risk text.", page=2),
    ]
    pi = build_page_index(ldus, "doc1", 5)
    assert len(pi.root.child_sections) == 2
    assert pi.root.child_sections[0].title == "1. Intro"
    assert pi.root.child_sections[0].page_start == 1
    assert pi.root.child_sections[0].page_end == 1
    assert set(pi.root.child_sections[0].ldu_ids) == {"l1", "l2"}
    assert pi.root.child_sections[1].title == "2. Risks"
    assert pi.root.child_sections[1].page_start == 2
    assert "paragraphs" in pi.root.child_sections[0].data_types_present


def test_build_deterministic_with_stub_summarizer():
    ldus = [
        _ldu("l1", "doc1", LDUContentType.SECTION_INTRO, "1. A", page=1),
        _ldu("l2", "doc1", LDUContentType.PARAGRAPH, "Content.", page=1),
    ]
    pi1 = build_page_index(ldus, "doc1", 2, summarizer=StubSummarizer())
    pi2 = build_page_index(ldus, "doc1", 2, summarizer=StubSummarizer())
    assert pi1.root.child_sections[0].summary is None
    assert pi2.root.child_sections[0].summary is None
    assert pi1.root.child_sections[0].id == pi2.root.child_sections[0].id


def test_write_and_load_pageindex(tmp_path):
    ldus = [
        _ldu("l1", "doc1", LDUContentType.SECTION_INTRO, "1. Section", page=1),
        _ldu("l2", "doc1", LDUContentType.PARAGRAPH, "Body.", page=1),
    ]
    pi = build_page_index(ldus, "doc1", 2)
    path = write_pageindex(pi, tmp_path)
    assert path == tmp_path / "doc1.json"
    assert path.exists()
    pi2 = load_pageindex(path)
    assert pi2.document_id == pi.document_id
    assert pi2.page_count == pi.page_count
    assert len(pi2.root.child_sections) == len(pi.root.child_sections)
    assert pi2.root.child_sections[0].page_start == 1
    assert pi2.root.child_sections[0].ldu_ids == ["l1", "l2"]


def test_pageindex_query_returns_top_n():
    ldus = [
        _ldu("l1", "doc1", LDUContentType.SECTION_INTRO, "1. Introduction", page=1),
        _ldu("l2", "doc1", LDUContentType.SECTION_HEADER, "2. Risk Factors", page=2),
    ]
    pi = build_page_index(ldus, "doc1", 3)
    top = pageindex_query("risk factors", page_index=pi, top_n=3)
    assert len(top) <= 3
    assert any(s.title == "2. Risk Factors" for s in top)
    top2 = pageindex_query("introduction", page_index=pi, top_n=2)
    assert len(top2) <= 2


def test_get_default_summarizer_openrouter(monkeypatch):
    from src.agents.indexer import get_default_summarizer, LLMSummarizer

    monkeypatch.setenv("REFINERY_VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    summarizer = get_default_summarizer()
    assert isinstance(summarizer, LLMSummarizer)


def test_get_default_summarizer_no_api_key(monkeypatch):
    from src.agents.indexer import get_default_summarizer, StubSummarizer

    monkeypatch.setenv("REFINERY_VISION_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("REFINERY_VISION_API_KEY", raising=False)
    summarizer = get_default_summarizer()
    assert isinstance(summarizer, StubSummarizer)
