# Semantic Chunking Engine — entry point per Refinery Guide §8 Deliverables.
# Implementation: src/chunking/ (ChunkValidator, ChunkingEngine). Builds LDUs from ExtractedDocument.

from __future__ import annotations

from src.chunking import ChunkValidator, ChunkingEngine, emit_ldus
from src.models import ExtractedDocument, LDU

def chunk_extracted_document(
    doc: ExtractedDocument,
    *,
    max_tokens: int = 800,
    reject_missing_parent_section: bool = True,
) -> list[LDU]:
    """Convenience wrapper: ExtractedDocument -> validated LDUs."""
    engine = ChunkingEngine(max_tokens=max_tokens, reject_missing_parent_section=reject_missing_parent_section)
    return engine.chunk(doc)


__all__ = ["ChunkValidator", "ChunkingEngine", "chunk_extracted_document", "emit_ldus"]
