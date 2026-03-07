# Data layer: FactTable (SQLite), vector store (Phase 4).

from .fact_table import (
    DEFAULT_FACT_TABLE_PATH,
    init_fact_table,
    extract_facts_from_ldus,
    build_source_reference,
    FactRecord,
)
from .vector_store import (
    DEFAULT_VECTOR_STORE_PATH,
    ingest_ldus as vector_store_ingest_ldus,
    search as vector_store_search,
)

__all__ = [
    "DEFAULT_FACT_TABLE_PATH",
    "init_fact_table",
    "extract_facts_from_ldus",
    "build_source_reference",
    "FactRecord",
    "DEFAULT_VECTOR_STORE_PATH",
    "vector_store_ingest_ldus",
    "vector_store_search",
]
