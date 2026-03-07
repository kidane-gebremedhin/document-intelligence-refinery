# Unit tests for FactTable SQLite schema and fact extraction. P4-T001.

import json
import sqlite3
from pathlib import Path

import pytest

from src.models import (
    BoundingBox,
    LDU,
    LDUContentType,
    PageRef,
    compute_content_hash,
)
from src.data.fact_table import (
    init_fact_table,
    extract_facts_from_ldus,
    build_source_reference,
    get_source_reference_provenance,
    DEFAULT_FACT_TABLE_PATH,
    FactRecord,
)


def _bbox() -> BoundingBox:
    return BoundingBox(x0=10.0, y0=20.0, x1=110.0, y1=40.0)


def _table_ldu(
    id_: str = "ldu_table_1",
    document_id: str = "doc1",
    page: int = 42,
    header: list[str] | None = None,
    rows: list[list[str | int]] | None = None,
) -> LDU:
    header = header or ["Metric", "Q1", "Q2"]
    rows = rows or [["Revenue", "100", "200"], ["Cost", "50", "75"]]
    raw = {"header": header, "rows": rows}
    text = ""
    content_hash = compute_content_hash(LDUContentType.TABLE.value, text, raw)
    return LDU(
        id=id_,
        document_id=document_id,
        content_type=LDUContentType.TABLE,
        text=text,
        raw_payload=raw,
        page_refs=[PageRef(document_id=document_id, page_number=page)],
        bounding_boxes=[_bbox()],
        token_count=10,
        content_hash=content_hash,
    )


def test_init_fact_table_creates_table_and_indexes(tmp_path: Path) -> None:
    path = init_fact_table(tmp_path / "facts.db")
    assert path.exists()
    conn = sqlite3.connect(path)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
    )
    assert cur.fetchone() is not None
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_facts_%'"
    )
    indexes = [r[0] for r in cur.fetchall()]
    conn.close()
    assert "idx_facts_document_id" in indexes
    assert "idx_facts_metric_period" in indexes
    assert "idx_facts_entity_metric" in indexes
    assert "idx_facts_source_page" in indexes


def test_insert_and_select_fact_with_source_reference(tmp_path: Path) -> None:
    path = init_fact_table(tmp_path / "facts.db")
    conn = sqlite3.connect(path)
    ref = build_source_reference("doc1", 42, "ldu_01", "abc123", (10.0, 20.0, 110.0, 40.0))
    conn.execute(
        """INSERT INTO facts (document_id, entity, metric, value, unit, period, category_path, source_reference, source_page, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("doc1", "Company", "revenue", "4.2B", "USD", "Q3 2024", None, ref, 42, "2024-01-01T00:00:00Z"),
    )
    conn.commit()
    cur = conn.execute("SELECT document_id, entity, metric, value, source_reference, source_page FROM facts LIMIT 1")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "doc1"
    assert row[1] == "Company"
    assert row[2] == "revenue"
    assert row[3] == "4.2B"
    assert row[5] == 42
    parsed = get_source_reference_provenance(row[4])
    assert parsed.get("document_id") == "doc1"
    assert parsed.get("page") == 42
    assert parsed.get("ldu_id") == "ldu_01"
    assert parsed.get("content_hash") == "abc123"
    assert parsed.get("bbox") == [10.0, 20.0, 110.0, 40.0]


def test_insert_without_source_reference_fails(tmp_path: Path) -> None:
    path = init_fact_table(tmp_path / "facts.db")
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO facts (document_id, entity, metric, value, source_reference)
               VALUES (?, ?, ?, ?, ?)""",
            ("doc1", "X", "m", "1", None),
        )
        conn.commit()
    conn.close()


def test_extract_facts_from_ldus_table_fixture(tmp_path: Path) -> None:
    ldu = _table_ldu("t1", "doc_fixture", page=7)
    db_path = tmp_path / "fact_table.db"
    init_fact_table(db_path)
    n = extract_facts_from_ldus([ldu], db_path, enabled=True)
    assert n > 0
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT document_id, entity, metric, value, source_reference, source_page FROM facts WHERE document_id = ?",
        ("doc_fixture",),
    )
    rows = cur.fetchall()
    conn.close()
    assert len(rows) == n
    for r in rows:
        doc_id, entity, metric, value, ref, page = r
        assert doc_id == "doc_fixture"
        assert page == 7
        parsed = json.loads(ref)
        assert parsed["document_id"] == "doc_fixture"
        assert parsed["page"] == 7
        assert parsed["ldu_id"] == "t1"
        assert "content_hash" in parsed
        assert "bbox" in parsed


def test_extract_facts_disabled_returns_zero(tmp_path: Path) -> None:
    ldu = _table_ldu()
    db_path = tmp_path / "fact_table.db"
    init_fact_table(db_path)
    n = extract_facts_from_ldus([ldu], db_path, enabled=False)
    assert n == 0
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT COUNT(*) FROM facts")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_extract_facts_paragraph_ldu_ignored(tmp_path: Path) -> None:
    from src.models import LDU, LDUContentType, PageRef, compute_content_hash
    para = LDU(
        id="p1",
        document_id="doc1",
        content_type=LDUContentType.PARAGRAPH,
        text="Revenue was 100.",
        page_refs=[PageRef(document_id="doc1", page_number=1)],
        bounding_boxes=[_bbox()],
        token_count=3,
        content_hash=compute_content_hash("paragraph", "Revenue was 100."),
    )
    db_path = tmp_path / "fact_table.db"
    init_fact_table(db_path)
    n = extract_facts_from_ldus([para], db_path, enabled=True, table_only=True)
    assert n == 0
