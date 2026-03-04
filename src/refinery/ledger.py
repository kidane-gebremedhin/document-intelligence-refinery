# Append-only extraction ledger (JSONL). Plan §5.2; spec 07 §9.1.

from __future__ import annotations

import json
from pathlib import Path

from src.models import ExtractionLedgerEntry

DEFAULT_LEDGER_PATH = Path(".refinery/extraction_ledger.jsonl")


def append_ledger_entry(
    entry: ExtractionLedgerEntry,
    ledger_path: Path | str | None = None,
) -> None:
    """Append one serialized ExtractionLedgerEntry as a single JSON line to the ledger file.

    Creates the ledger directory (e.g. .refinery) if it does not exist.
    Append-only: never overwrites or deletes existing lines.
    Each line is one JSON object (ISO 8601 datetimes). Safe for concurrent
    appends from multiple processes if the OS supports atomic append.
    """
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = entry.model_dump(mode="json")
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
