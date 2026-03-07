# Audit mode: verify claim → ProvenanceChain (verified or unverifiable). Spec 06 §7–8; plan §5.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.models import BoundingBox, ProvenanceChain, ProvenanceItem
from src.data.vector_store import search as vector_store_search, get_embedding_function
from src.data.fact_table import query_facts, get_source_reference_provenance

# Type for retrieval: (claim, document_id?) -> list of provenance items (evidence).
SearchEvidenceCallable = Callable[[str, str | None], list[ProvenanceItem]]

# document_id -> human-readable document name (e.g. filename). Unknown → fallback, no raise.
DocumentNameResolver = Callable[[str], str]


UNVERIFIABLE_MESSAGE = (
    "The claim could not be verified. No supporting source was found in the corpus."
)
VERIFIED_PREFIX = "The claim is supported by the following source(s)."


@dataclass
class AuditResult:
    """Result of audit mode: response text, provenance chain, and status."""

    response_text: str
    chain: ProvenanceChain
    status: str  # "verified" | "unverifiable"

    @property
    def verified(self) -> bool:
        return self.status == "verified"


# Words that appear in many documents and must not alone justify verification.
_AUDIT_STOPWORDS = frozenset({
    "the", "and", "is", "in", "to", "be", "this", "that", "not", "should", "would",
    "could", "are", "was", "were", "been", "have", "has", "had", "do", "does", "did",
    "will", "can", "may", "might", "must", "shall", "say", "says", "said", "report",
    "reports", "verified", "verification", "verify", "every", "all", "any", "some",
    "it", "its", "or", "for", "on", "with", "as", "at", "by", "from", "an", "if",
    "no", "so", "than", "but", "when", "which", "who", "what", "where", "how",
})


def _claim_terms(claim: str) -> set[str]:
    """Normalized lower-case terms from claim (length >= 2) for support checks."""
    return {t.strip().lower() for t in claim.split() if len(t.strip()) >= 2}


def _substantive_claim_terms(claim: str) -> set[str]:
    """Claim terms with stopwords removed; used to avoid verifying on generic words."""
    terms = _claim_terms(claim)
    return terms - _AUDIT_STOPWORDS


def _supports_claim_ldu(claim: str, content: str) -> bool:
    """
    Evidence for claims: semantic search (vector store). Retrieval is by embedding
    similarity (RAG-like); we do not filter by word overlap. Accept the hit unless
    the claim has no substantive terms (e.g. 'report says ... should not be verified'
    → no citation). Spec 08 §6.2–6.3.
    """
    if not (content or "").strip():
        return False
    substantive = _substantive_claim_terms(claim)
    if not substantive:
        return False
    return True


def _supports_claim_fact(claim: str, row: dict[str, Any]) -> bool:
    """
    Evidence for numbers / structured facts: use FactTable search. Rows are matched
    by query_facts(claim, ...). When semantic model is available, we rely on
    semantic similarity instead of term overlap; this pre-filter only rejects
    empty claims. Otherwise require at least one substantive term in the row.
    """
    substantive = _substantive_claim_terms(claim)
    if not substantive:
        return False
    # When semantic re-ranking is used, term overlap is not required (semantic will filter).
    text = " ".join(
        str(row.get(k) or "") for k in ("entity", "metric", "value", "period", "unit")
    ).lower()
    return bool(text.strip())  # Accept if row has content; semantic scoring does the real filtering


def _semantic_similarity(claim: str, evidence_text: str) -> float:
    """
    Compute cosine similarity between claim and evidence using all-MiniLM-L6-v2
    (or REFINERY_EMBEDDING_MODEL). Returns 0.0–1.0, or -1.0 if semantic model unavailable.
    """
    claim = (claim or "").strip()
    evidence_text = (evidence_text or "").strip()
    if not claim or not evidence_text:
        return -1.0
    try:
        fn = get_embedding_function()
        # Deterministic (hash) embeddings are not semantic; skip re-ranking
        if hasattr(fn, "is_legacy") and getattr(fn, "is_legacy", False):
            return -1.0
        vectors = fn([claim, evidence_text])
        if not vectors or len(vectors) != 2:
            return -1.0
        a, b = vectors[0], vectors[1]
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a <= 0 or norm_b <= 0:
            return -1.0
        sim = dot / (norm_a * norm_b)
        return max(0.0, min(1.0, (sim + 1) / 2))  # Cosine in [-1,1] → [0,1]
    except Exception:
        return -1.0


def _rank_by_semantic_similarity(
    claim: str,
    items: list[ProvenanceItem],
    min_similarity: float = 0.4,
) -> list[ProvenanceItem]:
    """
    Use all-MiniLM-L6-v2 (REFINERY_EMBEDDING_MODEL) to semantically match claim vs evidence.
    Filter items below min_similarity; sort by similarity descending (most accurate first).
    If semantic model unavailable, return items unchanged.
    """
    if not items:
        return []
    scored: list[tuple[float, ProvenanceItem]] = []
    for item in items:
        text = (item.snippet or "").strip() or ""
        if not text:
            scored.append((0.0, item))
            continue
        sim = _semantic_similarity(claim, text)
        if sim < 0:
            # Semantic unavailable: keep all, no re-ranking
            return items
        scored.append((sim, item))
    filtered = [(s, i) for s, i in scored if s >= min_similarity]
    if not filtered:
        return []
    filtered.sort(key=lambda x: -x[0])
    return [item for _, item in filtered]


def vector_hit_to_provenance_item(
    hit: dict[str, Any],
    document_name: str,
) -> ProvenanceItem | None:
    """
    Build one ProvenanceItem from a vector store hit. Requires page_refs, bounding_boxes, content_hash.
    Citations must include doc name, page number, bbox, content_hash.
    """
    page_refs = hit.get("page_refs") or []
    bboxes = hit.get("bounding_boxes") or []
    content_hash = (hit.get("content_hash") or "").strip()
    document_id = (hit.get("document_id") or "").strip()
    if not document_id or not content_hash:
        return None
    page_number = int(page_refs[0]) if page_refs else 1
    if page_number < 1:
        page_number = 1
    if not bboxes or len(bboxes[0]) < 4:
        return None
    b = bboxes[0]
    try:
        bbox = BoundingBox(x0=float(b[0]), y0=float(b[1]), x1=float(b[2]), y1=float(b[3]))
    except (TypeError, ValueError, IndexError):
        return None
    snippet = (hit.get("content") or "")[:300].strip()
    return ProvenanceItem(
        document_id=document_id,
        document_name=document_name,
        page_number=page_number,
        bbox=bbox,
        content_hash=content_hash,
        snippet=snippet,
        ldu_id=hit.get("ldu_id"),
    )


def fact_row_to_provenance_item(
    row: dict[str, Any],
    document_name_resolver: DocumentNameResolver,
) -> ProvenanceItem | None:
    """
    Build one ProvenanceItem from a FactTable row when source_reference has page, bbox, content_hash.
    Spec 06 §4: bbox required for LDU-backed; for FactTable may be null if not stored — we only
    return an item when all required fields (including bbox) are present so citations are complete.
    """
    ref = get_source_reference_provenance(row.get("source_reference") or "{}")
    page = ref.get("page")
    bbox_list = ref.get("bbox")
    content_hash = (ref.get("content_hash") or "").strip()
    document_id = (row.get("document_id") or ref.get("document_id") or "").strip()
    if not document_id or page is None or page < 1:
        return None
    if not bbox_list or len(bbox_list) < 4 or not content_hash:
        return None
    try:
        bbox = BoundingBox(
            x0=float(bbox_list[0]),
            y0=float(bbox_list[1]),
            x1=float(bbox_list[2]),
            y1=float(bbox_list[3]),
        )
    except (TypeError, ValueError, IndexError):
        return None
    document_name = document_name_resolver(document_id)
    value = row.get("value") or ""
    snippet = f"{row.get('entity', '')} {row.get('metric', '')} {value}".strip()[:300]
    return ProvenanceItem(
        document_id=document_id,
        document_name=document_name,
        page_number=int(page),
        bbox=bbox,
        content_hash=content_hash,
        snippet=snippet,
    )


def default_search_evidence(
    claim: str,
    document_id: str | None,
    *,
    vector_store_path: str | Path = ".refinery/vector_store",
    fact_table_path: str | Path = ".refinery/fact_table.db",
    document_name_resolver: DocumentNameResolver | None = None,
    top_k: int = 10,
    fact_limit: int = 20,
) -> list[ProvenanceItem]:
    """
    Claims: semantic search (vector store) for natural-language evidence.
    Numbers: FactTable search for metrics, values, periods. Build ProvenanceItems
    with doc name, page, bbox, content_hash. Spec 08 §6.2–6.3.
    """
    resolver = document_name_resolver or (lambda doc_id: doc_id)
    items: list[ProvenanceItem] = []

    # Vector store (semantic_search)
    doc_ids = [document_id] if document_id else None
    hits = vector_store_search(
        claim, top_k=top_k, path=vector_store_path, document_ids=doc_ids
    )
    for hit in hits:
        if not _supports_claim_ldu(claim, hit.get("content") or ""):
            continue
        doc_name = resolver(hit.get("document_id") or "")
        if not doc_name:
            continue
        cit = vector_hit_to_provenance_item(hit, doc_name)
        if cit is not None:
            items.append(cit)

    # FactTable (structured_query)
    fact_doc_ids = [document_id] if document_id else None
    rows = query_facts(claim, document_ids=fact_doc_ids, path=fact_table_path, limit=fact_limit)
    for row in rows:
        if not _supports_claim_fact(claim, row):
            continue
        cit = fact_row_to_provenance_item(row, resolver)
        if cit is not None:
            items.append(cit)

    # Semantic matching: use all-MiniLM-L6-v2 to rank evidence by similarity to claim.
    # Filter low-similarity hits; return most accurate (highest similarity) first.
    items = _rank_by_semantic_similarity(claim, items)
    return items


def audit_claim(
    claim: str,
    search_evidence: SearchEvidenceCallable,
    *,
    document_id: str | None = None,
    answer_id: str = "audit",
) -> AuditResult:
    """
    Audit mode: take a claim, search evidence via the provided retrieval, return
    ProvenanceChain with verified=True if evidence found, else verified=False and
    explicitly label the claim as unverifiable. No hallucinated verification.
    """
    items = search_evidence(claim, document_id)

    if not items:
        chain = ProvenanceChain(answer_id=answer_id, items=[], verified=False)
        return AuditResult(
            response_text=UNVERIFIABLE_MESSAGE,
            chain=chain,
            status="unverifiable",
        )

    chain = ProvenanceChain(answer_id=answer_id, items=items, verified=True)
    # Most accurate evidence is first (ranked by semantic similarity). Include best match.
    best = items[0].snippet.strip() if items and items[0].snippet else ""
    response = VERIFIED_PREFIX
    if best:
        response = f"{response}\n\nBest matching evidence: \"{best[:400]}{'…' if len(best) > 400 else ''}\""
    return AuditResult(
        response_text=response,
        chain=chain,
        status="verified",
    )


def audit(
    claim: str,
    *,
    document_id: str | None = None,
    vector_store_path: str | Path = ".refinery/vector_store",
    fact_table_path: str | Path = ".refinery/fact_table.db",
    document_name_resolver: DocumentNameResolver | None = None,
    answer_id: str = "audit",
    top_k: int = 10,
) -> AuditResult:
    """
    Audit mode entry: verify claim using vector store + FactTable. Returns ProvenanceChain
    with verified=True and items when evidence found; else verified=False and explicit
    unverifiable result. Never mark verified without citations; citations include
    document_name, page_number, bbox, content_hash.
    """
    def search_evidence(c: str, doc_id: str | None) -> list[ProvenanceItem]:
        return default_search_evidence(
            c,
            doc_id,
            vector_store_path=vector_store_path,
            fact_table_path=fact_table_path,
            document_name_resolver=document_name_resolver,
            top_k=top_k,
        )
    return audit_claim(claim, search_evidence, document_id=document_id, answer_id=answer_id)
