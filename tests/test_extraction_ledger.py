# Unit tests for ExtractionLedgerEntry and ledger append. Task: P2-T007.

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.models import ExtractionLedgerEntry
from src.refinery.ledger import append_ledger_entry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_ledger_entry_valid_roundtrip():
    """ExtractionLedgerEntry validates and round-trips to JSON."""
    start = _utc_now()
    end = start
    entry = ExtractionLedgerEntry(
        document_id="doc1",
        strategy_used="fast_text",
        origin_type="native_digital",
        layout_complexity="single_column",
        start_time=start,
        end_time=end,
        processing_time_ms=100,
        confidence_score=0.9,
        cost_estimate_usd=0.0,
        escalation_chain=["fast_text"],
        notes=None,
    )
    data = entry.model_dump(mode="json")
    back = ExtractionLedgerEntry.model_validate(data)
    assert back.document_id == entry.document_id
    assert back.strategy_used == entry.strategy_used
    assert back.escalation_chain == ["fast_text"]


def test_ledger_entry_rejects_end_time_before_start_time():
    """end_time must be >= start_time."""
    start = _utc_now()
    end_before = start - timedelta(seconds=1)
    with pytest.raises(Exception):  # ValidationError
        ExtractionLedgerEntry(
            document_id="doc1",
            strategy_used="fast_text",
            origin_type="native_digital",
            layout_complexity="single_column",
            start_time=start,
            end_time=end_before,
            processing_time_ms=100,
            confidence_score=0.9,
            cost_estimate_usd=0.0,
            escalation_chain=["fast_text"],
        )


def test_ledger_entry_strategy_used_must_match_last_in_escalation_chain():
    """When strategy_used is not escalation_failed, it must equal last element of escalation_chain."""
    start = _utc_now()
    with pytest.raises(Exception):
        ExtractionLedgerEntry(
            document_id="doc1",
            strategy_used="layout",
            origin_type="native_digital",
            layout_complexity="single_column",
            start_time=start,
            end_time=start,
            processing_time_ms=100,
            confidence_score=0.8,
            cost_estimate_usd=0.0,
            escalation_chain=["fast_text"],
        )


def test_ledger_entry_escalation_failed_allowed():
    """strategy_used escalation_failed is allowed with any escalation_chain."""
    start = _utc_now()
    entry = ExtractionLedgerEntry(
        document_id="doc1",
        strategy_used="escalation_failed",
        origin_type="native_digital",
        layout_complexity="multi_column",
        start_time=start,
        end_time=start,
        processing_time_ms=500,
        confidence_score=0.3,
        cost_estimate_usd=0.0,
        escalation_chain=["fast_text", "layout"],
        notes="confidence_below_threshold",
    )
    assert entry.strategy_used == "escalation_failed"


def test_append_ledger_entry_creates_dir_and_writes_jsonl(tmp_path: Path):
    """Appending creates parent dir if missing and writes valid JSONL; second append adds a line."""
    ledger_file = tmp_path / "subdir" / "extraction_ledger.jsonl"
    assert not ledger_file.parent.exists()

    start = _utc_now()
    entry1 = ExtractionLedgerEntry(
        document_id="doc1",
        strategy_used="fast_text",
        origin_type="native_digital",
        layout_complexity="single_column",
        start_time=start,
        end_time=start,
        processing_time_ms=50,
        confidence_score=0.95,
        cost_estimate_usd=0.0,
        escalation_chain=["fast_text"],
    )
    append_ledger_entry(entry1, ledger_path=ledger_file)
    assert ledger_file.parent.exists()
    assert ledger_file.exists()

    lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    obj1 = json.loads(lines[0])
    assert obj1["document_id"] == "doc1"
    assert obj1["strategy_used"] == "fast_text"
    assert obj1["confidence_score"] == 0.95
    assert obj1["escalation_chain"] == ["fast_text"]
    assert "start_time" in obj1 and "end_time" in obj1

    entry2 = ExtractionLedgerEntry(
        document_id="doc2",
        strategy_used="layout",
        origin_type="mixed",
        layout_complexity="table_heavy",
        start_time=start,
        end_time=start,
        processing_time_ms=200,
        confidence_score=0.85,
        cost_estimate_usd=0.0,
        escalation_chain=["layout"],
    )
    append_ledger_entry(entry2, ledger_path=ledger_file)
    lines2 = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines2) == 2
    obj2 = json.loads(lines2[1])
    assert obj2["document_id"] == "doc2"
    assert obj2["strategy_used"] == "layout"
    assert obj2["confidence_score"] == 0.85
    assert obj2["escalation_chain"] == ["layout"]

    assert json.loads(lines2[0])["document_id"] == "doc1"
