# Query Interface Agent — LangGraph with three tools. Spec 06 §3; plan §2.1.

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from src.models import ProvenanceChain, ProvenanceItem
from src.agents.indexer import load_pageindex, pageindex_query, DEFAULT_PAGEINDEX_DIR
from src.data.vector_store import search as vector_store_search, DEFAULT_VECTOR_STORE_PATH
from src.data.fact_table import query_facts, DEFAULT_FACT_TABLE_PATH
from src.agents.audit import (
    fact_row_to_provenance_item,
    vector_hit_to_provenance_item,
)

DocumentNameResolver = Callable[[str], str]


# -----------------------------------------------------------------------------
# Tool output types (typed and serializable)
# -----------------------------------------------------------------------------


class SectionSummary(BaseModel):
    """One section from pageindex_navigate. Serializable."""

    id: str = Field(..., description="Section id.")
    document_id: str = Field(..., description="Document id.")
    title: str = Field(default="", description="Section title.")
    page_start: int = Field(..., ge=1)
    page_end: int = Field(..., ge=1)
    summary: str | None = Field(default=None)
    ldu_ids: list[str] = Field(default_factory=list, description="LDU ids in this section.")


class PageIndexNavigateResult(BaseModel):
    """Output of pageindex_navigate tool."""

    sections: list[SectionSummary] = Field(default_factory=list)
    document_id: str | None = Field(default=None, description="Document filtered, if any.")


class SemanticSearchResult(BaseModel):
    """Output of semantic_search tool. Each hit has content and provenance fields."""

    hits: list[dict[str, Any]] = Field(default_factory=list)
    query: str = Field(default="")
    top_k: int = Field(default=5)


class StructuredQueryResult(BaseModel):
    """Output of structured_query tool. Rows have entity, metric, value, source_reference."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    query: str = Field(default="")


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------


def pageindex_navigate(
    topic: str,
    document_id: str | None = None,
    top_n: int = 3,
    pageindex_dir: str | Path = DEFAULT_PAGEINDEX_DIR,
) -> PageIndexNavigateResult:
    """
    Traverse PageIndex by topic; return top-N sections with id, title, page_start, page_end, summary, ldu_ids.
    Spec 06 §3.1.
    """
    pageindex_dir = Path(pageindex_dir)
    if not pageindex_dir.exists():
        return PageIndexNavigateResult(document_id=document_id)
    if document_id:
        path = pageindex_dir / f"{document_id}.json"
        if not path.exists():
            return PageIndexNavigateResult(document_id=document_id)
        sections = pageindex_query(topic, path=path, document_id=document_id, top_n=top_n)
    else:
        sections = []
        for p in sorted(pageindex_dir.glob("*.json")):
            try:
                sections = pageindex_query(topic, path=p, top_n=top_n)
                if sections:
                    break
            except Exception:
                continue
    summaries = [
        SectionSummary(
            id=s.id,
            document_id=s.document_id,
            title=s.title or "",
            page_start=s.page_start,
            page_end=s.page_end,
            summary=s.summary,
            ldu_ids=list(s.ldu_ids or []),
        )
        for s in sections
    ]
    return PageIndexNavigateResult(sections=summaries, document_id=document_id)


def semantic_search(
    query: str,
    document_ids: list[str] | None = None,
    section_constraint: list[str] | None = None,
    top_k: int = 5,
    vector_store_path: str | Path = DEFAULT_VECTOR_STORE_PATH,
) -> SemanticSearchResult:
    """
    Retrieve LDUs by semantic similarity. Returns hits with content, document_id, ldu_id, page_refs, bounding_boxes, content_hash.
    Spec 06 §3.2.
    """
    hits = vector_store_search(
        query,
        top_k=top_k,
        path=vector_store_path,
        document_ids=document_ids,
        section_constraint=section_constraint,
    )
    return SemanticSearchResult(hits=hits, query=query, top_k=top_k)


def structured_query(
    query: str,
    document_ids: list[str] | None = None,
    limit: int = 20,
    fact_table_path: str | Path = DEFAULT_FACT_TABLE_PATH,
) -> StructuredQueryResult:
    """
    Safe parameterized query over FactTable. Returns rows with entity, metric, value, unit, period, source_reference.
    Spec 06 §3.3, 08 §5.
    """
    rows = query_facts(query, document_ids=document_ids, path=fact_table_path, limit=limit)
    return StructuredQueryResult(rows=rows, query=query)


# -----------------------------------------------------------------------------
# Provenance from tool results
# -----------------------------------------------------------------------------


def _build_provenance_from_state(
    state: dict[str, Any],
    document_name_resolver: DocumentNameResolver,
) -> tuple[list[ProvenanceItem], bool]:
    """Build list of ProvenanceItems from search/structured results; verified = at least one citation."""
    resolver = document_name_resolver or (lambda doc_id: doc_id)
    items: list[ProvenanceItem] = []
    seen: set[tuple[str, int, str]] = set()

    search_result = state.get("search_result") or {}
    for hit in search_result.get("hits", []):
        doc_id = hit.get("document_id") or ""
        doc_name = resolver(doc_id)
        if not doc_name:
            continue
        cit = vector_hit_to_provenance_item(hit, doc_name)
        if cit is None:
            continue
        key = (cit.document_id, cit.page_number, cit.content_hash)
        if key in seen:
            continue
        seen.add(key)
        items.append(cit)

    structured_result = state.get("structured_result") or {}
    for row in structured_result.get("rows", []):
        cit = fact_row_to_provenance_item(row, resolver)
        if cit is None:
            continue
        key = (cit.document_id, cit.page_number, cit.content_hash)
        if key in seen:
            continue
        seen.add(key)
        items.append(cit)

    return items, len(items) > 0


# -----------------------------------------------------------------------------
# LangGraph nodes and graph
# -----------------------------------------------------------------------------


def _retrieve_node(
    state: dict[str, Any],
    *,
    pageindex_dir: Path,
    vector_store_path: Path,
    fact_table_path: Path,
    top_k: int,
    top_n: int,
) -> dict[str, Any]:
    """Run all three tools and populate state with results."""
    query = state.get("query") or ""
    document_id = state.get("document_id")
    doc_ids = [document_id] if document_id else None

    nav = pageindex_navigate(query, document_id=document_id, top_n=top_n, pageindex_dir=pageindex_dir)
    section_constraint = []
    for s in nav.sections:
        section_constraint.extend(s.ldu_ids)
    if document_id and nav.sections:
        doc_ids = [document_id]

    search_res = semantic_search(
        query,
        document_ids=doc_ids,
        section_constraint=section_constraint if section_constraint else None,
        top_k=top_k,
        vector_store_path=vector_store_path,
    )
    struct_res = structured_query(
        query,
        document_ids=doc_ids,
        limit=20,
        fact_table_path=fact_table_path,
    )

    return {
        **state,
        "navigate_result": nav.model_dump(),
        "search_result": search_res.model_dump(),
        "structured_result": struct_res.model_dump(),
    }


def _synthesize_node(
    state: dict[str, Any],
    *,
    document_name_resolver: DocumentNameResolver | None,
    answer_id: str,
) -> dict[str, Any]:
    """Build answer text and ProvenanceChain from tool results."""
    query = state.get("query") or ""
    items, verified = _build_provenance_from_state(
        state, document_name_resolver or (lambda doc_id: doc_id)
    )
    chain = ProvenanceChain(answer_id=answer_id, items=items, verified=verified)

    hits = (state.get("search_result") or {}).get("hits", [])
    rows = (state.get("structured_result") or {}).get("rows", [])
    if not hits and not rows:
        answer = "No relevant content was found in the corpus for this query."
    else:
        parts = []
        for h in hits[:5]:
            content = (h.get("content") or "").strip()
            if content:
                parts.append(content[:500] + ("..." if len(content) > 500 else ""))
        for r in rows[:5]:
            entity = (r.get("entity") or "").strip()
            metric = (r.get("metric") or "").strip()
            value = (r.get("value") or "").strip()
            if entity or metric or value:
                parts.append(f"{entity} {metric}: {value}".strip())
        answer = "Based on the retrieved sources:\n\n" + "\n\n".join(parts[:6]) if parts else "No relevant content was found."

    return {
        **state,
        "answer": answer,
        "provenance_chain": chain.model_dump(),
        "verified": verified,
    }


def create_query_graph(
    *,
    pageindex_dir: str | Path = DEFAULT_PAGEINDEX_DIR,
    vector_store_path: str | Path = DEFAULT_VECTOR_STORE_PATH,
    fact_table_path: str | Path = DEFAULT_FACT_TABLE_PATH,
    top_k: int = 10,
    top_n: int = 5,
    document_name_resolver: DocumentNameResolver | None = None,
    answer_id: str = "query",
):
    """Build compiled LangGraph: START -> retrieve -> synthesize -> END."""
    from langgraph.graph import START, END, StateGraph

    pageindex_dir = Path(pageindex_dir)
    vector_store_path = Path(vector_store_path)
    fact_table_path = Path(fact_table_path)

    def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        return _retrieve_node(
            state,
            pageindex_dir=pageindex_dir,
            vector_store_path=vector_store_path,
            fact_table_path=fact_table_path,
            top_k=top_k,
            top_n=top_n,
        )

    def synthesize(state: dict[str, Any]) -> dict[str, Any]:
        return _synthesize_node(
            state,
            document_name_resolver=document_name_resolver,
            answer_id=answer_id,
        )

    builder = StateGraph(dict)
    builder.add_node("retrieve", retrieve)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile()


def query(
    question: str,
    document_id: str | None = None,
    *,
    pageindex_dir: str | Path = DEFAULT_PAGEINDEX_DIR,
    vector_store_path: str | Path = DEFAULT_VECTOR_STORE_PATH,
    fact_table_path: str | Path = DEFAULT_FACT_TABLE_PATH,
    top_k: int = 10,
    top_n: int = 5,
    document_name_resolver: DocumentNameResolver | None = None,
    graph=None,
) -> dict[str, Any]:
    """
    Run the query agent on a natural-language question. Returns dict with answer (str),
    provenance_chain (ProvenanceChain as dict), and verified (bool).
    """
    if graph is None:
        graph = create_query_graph(
            pageindex_dir=pageindex_dir,
            vector_store_path=vector_store_path,
            fact_table_path=fact_table_path,
            top_k=top_k,
            top_n=top_n,
            document_name_resolver=document_name_resolver,
        )
    state = {"query": question, "document_id": document_id}
    result = graph.invoke(state)
    return {
        "answer": result.get("answer", ""),
        "provenance_chain": result.get("provenance_chain", {}),
        "verified": result.get("verified", False),
    }


__all__ = [
    "SectionSummary",
    "PageIndexNavigateResult",
    "SemanticSearchResult",
    "StructuredQueryResult",
    "pageindex_navigate",
    "semantic_search",
    "structured_query",
    "create_query_graph",
    "query",
]
