# FactTable — SQLite schema, init, and fact extraction from LDUs. Spec 08 §2, §3.

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import LDU, LDUContentType

DEFAULT_FACT_TABLE_PATH = ".refinery/fact_table.db"

FACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    metric TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    period TEXT,
    category_path TEXT,
    source_reference TEXT NOT NULL,
    source_page INTEGER,
    created_at TEXT
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_facts_document_id ON facts(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_facts_metric_period ON facts(metric, period);",
    "CREATE INDEX IF NOT EXISTS idx_facts_entity_metric ON facts(entity, metric);",
    "CREATE INDEX IF NOT EXISTS idx_facts_source_page ON facts(document_id, source_page);",
]


@dataclass
class FactRecord:
    """One fact row for insertion or query result. Spec 08 §2.2, §3.2."""

    document_id: str
    entity: str
    metric: str
    value: str
    unit: str | None
    period: str | None
    category_path: str | None
    source_reference: str
    source_page: int | None = None
    created_at: str | None = None


def init_fact_table(path: str | Path = DEFAULT_FACT_TABLE_PATH) -> Path:
    """Create facts table and indexes if they do not exist. Returns path to DB."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(FACTS_SCHEMA)
        for idx_sql in INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    finally:
        conn.close()
    return path


def build_source_reference(
    document_id: str,
    page: int,
    ldu_id: str,
    content_hash: str,
    bbox: tuple[float, float, float, float] | None = None,
) -> str:
    """Build source_reference JSON with document_id, page, ldu_id, bbox, content_hash for provenance."""
    ref: dict[str, Any] = {
        "document_id": document_id,
        "page": page,
        "ldu_id": ldu_id,
        "content_hash": content_hash,
    }
    if bbox is not None:
        ref["bbox"] = list(bbox)
    return json.dumps(ref, sort_keys=True)


def _parse_source_reference(s: str) -> dict[str, Any]:
    """Parse source_reference JSON; return dict with document_id, page, ldu_id, bbox, content_hash."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def _first_page(ldu: LDU) -> int:
    if not ldu.page_refs:
        return 1
    return ldu.page_refs[0].page_number


def _first_bbox(ldu: LDU) -> tuple[float, float, float, float] | None:
    if not ldu.bounding_boxes:
        return None
    b = ldu.bounding_boxes[0]
    return (b.x0, b.y0, b.x1, b.y1)


def _extract_facts_from_table_ldu(ldu: LDU) -> list[FactRecord]:
    """Extract fact records from a single table LDU (raw_payload header/rows or text)."""
    records: list[FactRecord] = []
    doc_id = ldu.document_id
    page = _first_page(ldu)
    bbox = _first_bbox(ldu)
    source_ref = build_source_reference(doc_id, page, ldu.id, ldu.content_hash, bbox)

    rp = ldu.raw_payload or {}
    headers = rp.get("header") or rp.get("headers")
    rows = rp.get("rows") or rp.get("data") or []

    if isinstance(headers, list) and headers and rows:
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            for col_idx, cell in enumerate(row):
                if col_idx >= len(headers):
                    break
                metric = str(headers[col_idx]).strip() if headers[col_idx] else f"col_{col_idx}"
                value = str(cell).strip() if cell is not None else ""
                if not value:
                    continue
                entity = str(row[0]).strip() if row and len(row) > 0 else "Unknown"
                records.append(
                    FactRecord(
                        document_id=doc_id,
                        entity=entity,
                        metric=metric,
                        value=value,
                        unit=None,
                        period=None,
                        category_path=None,
                        source_reference=source_ref,
                        source_page=page,
                    )
                )
        return records

    text = (ldu.text or "").strip()
    if not text:
        return records
    lines = text.split("\n")
    if len(lines) < 2:
        return records
    header_parts = [p.strip() for p in lines[0].replace("\t", "|").split("|") if p.strip()]
    for line in lines[1:]:
        cells = [p.strip() for p in line.replace("\t", "|").split("|") if p.strip()]
        if not cells:
            continue
        entity = cells[0] if cells else "Unknown"
        for col_idx, cell in enumerate(cells):
            if col_idx >= len(header_parts):
                break
            if not cell:
                continue
            metric = header_parts[col_idx]
            records.append(
                FactRecord(
                    document_id=doc_id,
                    entity=entity,
                    metric=metric,
                    value=cell,
                    unit=None,
                    period=None,
                    category_path=None,
                    source_reference=source_ref,
                    source_page=page,
                )
            )
    return records


def _extract_keyvalue_facts_from_ldu(ldu: LDU) -> list[FactRecord]:
    """Extract key-value facts from paragraph/list LDUs (e.g. revenue: $4.2B, date: Q3 2024)."""
    records: list[FactRecord] = []
    text = (ldu.text or "").strip()
    if len(text) < 3:
        return records
    doc_id = ldu.document_id
    page = _first_page(ldu)
    bbox = _first_bbox(ldu)
    source_ref = build_source_reference(doc_id, page, ldu.id, ldu.content_hash, bbox)
    entity = "Document"

    # Label: value on same line
    for m in re.finditer(r"(?m)^\s*([A-Za-z][A-Za-z0-9\s\-]+?)\s*[:\-]\s*(.+?)\s*$", text):
        metric = m.group(1).strip()
        value = m.group(2).strip()
        if len(metric) > 50 or len(value) > 200:
            continue
        if re.match(r"^\d+$", metric):
            continue
        records.append(
            FactRecord(
                document_id=doc_id,
                entity=entity,
                metric=metric,
                value=value,
                unit=None,
                period=None,
                category_path=None,
                source_reference=source_ref,
                source_page=page,
            )
        )
    # Period / financial shorthand (Q3 2024, FY 2024) — at most one per LDU to avoid duplicates
    seen_period: set[str] = set()
    for m in re.finditer(r"(?i)(Q[1-4]\s*\d{4}|FY\s*\d{4})", text):
        period = m.group(1).strip()
        if period in seen_period:
            continue
        seen_period.add(period)
        records.append(
            FactRecord(
                document_id=doc_id,
                entity=entity,
                metric="period",
                value=period,
                unit=None,
                period=period,
                category_path=None,
                source_reference=source_ref,
                source_page=page,
            )
        )
    return records


def extract_facts_from_ldus(
    ldus: list[LDU],
    path: str | Path = DEFAULT_FACT_TABLE_PATH,
    *,
    enabled: bool = True,
    table_only: bool = False,
) -> int:
    """
    Extract facts from table LDUs and, when table_only=False, key-value facts from
    paragraph/list LDUs (e.g. revenue: $4.2B, date: Q3 2024). Insert into FactTable.
    Returns number of facts inserted. When enabled=False, returns 0 without writing.
    """
    if not enabled:
        return 0
    path = Path(path)
    if not path.exists():
        init_fact_table(path)
    table_types = (LDUContentType.TABLE, LDUContentType.TABLE_SECTION)
    kv_types = (LDUContentType.PARAGRAPH, LDUContentType.LIST)
    records: list[FactRecord] = []
    for ldu in ldus:
        if ldu.content_type in table_types:
            records.extend(_extract_facts_from_table_ldu(ldu))
        elif not table_only and ldu.content_type in kv_types:
            records.extend(_extract_keyvalue_facts_from_ldu(ldu))
    if not records:
        return 0
    conn = sqlite3.connect(path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        for r in records:
            conn.execute(
                """INSERT INTO facts (document_id, entity, metric, value, unit, period, category_path, source_reference, source_page, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.document_id,
                    r.entity,
                    r.metric,
                    r.value,
                    r.unit,
                    r.period,
                    r.category_path,
                    r.source_reference,
                    r.source_page,
                    now,
                ),
            )
        conn.commit()
        return len(records)
    finally:
        conn.close()


def get_source_reference_provenance(source_reference: str) -> dict[str, Any]:
    """Return document_id, page, ldu_id, bbox, content_hash from source_reference JSON."""
    return _parse_source_reference(source_reference)


def query_facts(
    query_text: str,
    document_ids: list[str] | None = None,
    path: str | Path = DEFAULT_FACT_TABLE_PATH,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Safe parameterized query over FactTable for audit/structured_query. Spec 08 §5.
    No raw SQL from user; query_text is used as LIKE-bound terms (space-separated).
    Returns list of rows with document_id, entity, metric, value, unit, period, source_reference, source_page.
    """
    path = Path(path)
    if not path.exists():
        return []
    # Sanitize: use only non-empty tokens for filtering; no raw SQL from user
    terms = [t.strip() for t in query_text.split() if t.strip()][:10]
    if not terms:
        return []
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            "SELECT document_id, entity, metric, value, unit, period, source_reference, source_page FROM facts"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    # Filter in Python to avoid SQL injection; optional document filter
    col_names = [
        "document_id", "entity", "metric", "value", "unit", "period",
        "source_reference", "source_page",
    ]
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(zip(col_names, row))
        if document_ids is not None and r["document_id"] not in document_ids:
            continue
        text = " ".join(
            str(r.get(k) or "") for k in ("entity", "metric", "value", "period")
        ).lower()
        if any(term.lower() in text for term in terms):
            out.append(r)
            if len(out) >= limit:
                break
    return out
