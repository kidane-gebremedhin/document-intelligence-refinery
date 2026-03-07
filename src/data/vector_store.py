# Vector store: ingest LDUs and query by text. Spec 08 §4 (ChromaDB).
# RAG-like semantic search when REFINERY_EMBEDDING_MODEL is set and sentence-transformers installed.

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from src.models import LDU

DEFAULT_VECTOR_STORE_PATH = ".refinery/vector_store"

# Reuse one client per path to avoid Chroma "already exists with different settings".
_chroma_client_cache: dict[str, Any] = {}
DEFAULT_COLLECTION_NAME = "ldu_chunks"
EMBEDDING_DIM = 384

# Optional semantic embedding model (e.g. all-MiniLM-L6-v2). Set REFINERY_EMBEDDING_MODEL to enable.
_SEMANTIC_EMBEDDING_FN: Any = None


def get_embedding_function(embedding_function: Any = None):
    """
    Return the embedding function for ingest and search. Same function must be used for both.
    If embedding_function is passed, use it. Else if REFINERY_EMBEDDING_MODEL is set and
    sentence-transformers is installed, use semantic embeddings; otherwise deterministic (hash-based).
    Re-ingest LDUs after switching from deterministic to semantic (or vice versa).
    """
    if embedding_function is not None:
        return embedding_function
    model = (os.environ.get("REFINERY_EMBEDDING_MODEL") or "").strip()
    if model:
        global _SEMANTIC_EMBEDDING_FN
        if _SEMANTIC_EMBEDDING_FN is None:
            try:
                from sentence_transformers import SentenceTransformer
                st = SentenceTransformer(model)
                # ChromaDB-compatible: __call__(input: list[str]) and embed_query(input: str | list[str])
                class _STWrapper:
                    def __call__(self, input: list[str]) -> list[list[float]]:
                        return st.encode(input, convert_to_numpy=True).tolist()
                    def embed_query(self, input: str | list[str]) -> list[list[float]]:
                        if isinstance(input, str):
                            input = [input]
                        return self(input)
                _SEMANTIC_EMBEDDING_FN = _STWrapper()
            except ImportError:
                pass
        if _SEMANTIC_EMBEDDING_FN is not None:
            return _SEMANTIC_EMBEDDING_FN
    return _DeterministicEmbeddingFunction()


def _deterministic_embedding(texts: list[str], dimension: int = EMBEDDING_DIM) -> list[list[float]]:
    """Deterministic embedding for tests and offline use: same text -> same vector. No network."""
    out: list[list[float]] = []
    for t in texts:
        h = hashlib.sha256((t or " ").encode("utf-8")).digest()
        vec = [((h[i % len(h)] ^ h[(i + 1) % len(h)]) / 255.0 - 0.5) for i in range(dimension)]
        total = sum(x * x for x in vec) ** 0.5
        if total > 0:
            vec = [x / total for x in vec]
        out.append(vec)
    return out


def _ldu_content(ldu: LDU) -> str:
    """Text to embed and store for retrieval."""
    if (ldu.text or "").strip():
        return ldu.text.strip()
    if ldu.raw_payload:
        return json.dumps(ldu.raw_payload, sort_keys=True)[:10000]
    return ""


def _page_refs_json(ldu: LDU) -> str:
    """Serialize page numbers for metadata (ChromaDB accepts str)."""
    pages = [p.page_number for p in ldu.page_refs]
    return json.dumps(pages)


def _bounding_boxes_json(ldu: LDU) -> str:
    """Serialize first bbox [x0,y0,x1,y1] or list of bboxes for metadata."""
    if not ldu.bounding_boxes:
        return "[]"
    boxes = [[b.x0, b.y0, b.x1, b.y1] for b in ldu.bounding_boxes]
    return json.dumps(boxes)


class _DeterministicEmbeddingFunction:
    """Offline embedding: same text -> same vector. No network. Spec 08 §4."""

    def name(self) -> str:
        return "deterministic"

    def is_legacy(self) -> bool:
        return True

    def __call__(self, input: list[str]) -> list[list[float]]:
        return _deterministic_embedding(input, EMBEDDING_DIM)

    def embed_query(self, input: str | list[str]) -> list[list[float]]:
        """Chroma uses this for query embedding. input can be single str or list."""
        if isinstance(input, str):
            input = [input]
        return _deterministic_embedding(input, EMBEDDING_DIM)


def _chroma_client(path: Path):
    """One client per resolved path; same Settings so Chroma does not raise."""
    import chromadb
    from chromadb.config import Settings

    key = str(path.resolve())
    if key not in _chroma_client_cache:
        _chroma_client_cache[key] = chromadb.PersistentClient(
            path=key, settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client_cache[key]


def ingest_ldus(
    ldus: list[LDU],
    path: str | Path = DEFAULT_VECTOR_STORE_PATH,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_function: Any = None,
) -> int:
    """
    Ingest LDUs into ChromaDB: embed text, store with metadata for provenance.
    Uses ldu.id as ChromaDB id for idempotent upsert. Returns count ingested.
    Embedding: set REFINERY_EMBEDDING_MODEL (e.g. all-MiniLM-L6-v2) and install
    sentence-transformers (uv sync --extra semantic) for RAG-like semantic search.
    """
    if not ldus:
        return 0
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    if embedding_function is None:
        embedding_function = get_embedding_function()
    client = _chroma_client(path)
    coll = client.get_or_create_collection(
        name=collection_name,
        metadata={"description": "LDU chunks"},
        embedding_function=embedding_function,
    )

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str | int | float | bool]] = []
    for ldu in ldus:
        content = _ldu_content(ldu)
        ids.append(ldu.id)
        documents.append(content or " ")
        page_refs_str = _page_refs_json(ldu)
        bboxes_str = _bounding_boxes_json(ldu)
        first_page = ldu.page_refs[0].page_number if ldu.page_refs else 0
        metadatas.append({
            "document_id": ldu.document_id,
            "ldu_id": ldu.id,
            "page_refs": page_refs_str,
            "bounding_boxes": bboxes_str,
            "content_hash": ldu.content_hash,
            "parent_section_id": ldu.parent_section_id or "",
            "chunk_type": ldu.content_type.value,
            "first_page": first_page,
        })
    coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(ldus)


def search(
    query_text: str,
    top_k: int = 5,
    path: str | Path = DEFAULT_VECTOR_STORE_PATH,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    document_ids: list[str] | None = None,
    section_constraint: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic search: embed query_text and return top-k nearest LDUs by vector similarity.
    Uses same embedding as ingest (REFINERY_EMBEDDING_MODEL or deterministic). Each result
    has: content, document_id, ldu_id, page_refs, bounding_boxes, content_hash, parent_section_id.
    """
    path = Path(path)
    if not path.exists():
        return []

    client = _chroma_client(path)
    try:
        coll = client.get_collection(
            name=collection_name,
            embedding_function=get_embedding_function(),
        )
    except Exception:
        return []

    where: dict[str, Any] | None = None
    if document_ids is not None and len(document_ids) == 1:
        where = {"document_id": document_ids[0]}
    elif document_ids is not None and len(document_ids) > 1:
        where = {"document_id": {"$in": document_ids}}
    if section_constraint:
        ldu_filter = {"ldu_id": {"$in": section_constraint}}
        if where is None:
            where = ldu_filter
        else:
            where = {"$and": [where, ldu_filter]}

    result = coll.query(
        query_texts=[query_text],
        n_results=min(top_k, 100),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    if not result or not result["ids"] or not result["ids"][0]:
        return []

    out: list[dict[str, Any]] = []
    for i, ldu_id in enumerate(result["ids"][0]):
        doc = result["documents"][0][i] if result["documents"] else ""
        meta = result["metadatas"][0][i] if result["metadatas"] else {}
        page_refs_str = meta.get("page_refs", "[]")
        bboxes_str = meta.get("bounding_boxes", "[]")
        try:
            page_refs = json.loads(page_refs_str)
        except (json.JSONDecodeError, TypeError):
            page_refs = []
        try:
            bboxes = json.loads(bboxes_str)
        except (json.JSONDecodeError, TypeError):
            bboxes = []
        out.append({
            "content": doc,
            "document_id": meta.get("document_id", ""),
            "ldu_id": meta.get("ldu_id", ldu_id),
            "page_refs": page_refs,
            "bounding_boxes": bboxes,
            "content_hash": meta.get("content_hash", ""),
            "parent_section_id": meta.get("parent_section_id") or None,
            "chunk_type": meta.get("chunk_type", ""),
        })
    return out
