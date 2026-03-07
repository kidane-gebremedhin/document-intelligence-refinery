# Spec: Data Layer — FactTable, Vector Store, structured_query & Audit Data Flow

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Upstream:** [04 – Semantic Chunking Engine & LDUs](04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](05-pageindex-builder-spec.md)  
**Consumers:** [06 – Query Agent & Provenance](06-query-agent-and-provenance-spec.md)  
**Constitution alignment:** Typed contracts; config-over-code for paths and thresholds; every answer and audit result traceable to stored data (FactTable, vector store, LDUs).

---

## 1. Purpose

The **Data Layer** is the persistence and query surface that sits between the pipeline outputs (LDUs, PageIndex) and the Query Interface Agent. It comprises:

1. **FactTable** — SQLite-backed store of structured numerical/factual facts extracted from LDUs; queried by `structured_query`.
2. **Vector store** — ChromaDB-backed store of LDU embeddings for semantic search; populated by LDU ingestion after Stage 3.
3. **structured_query tool contract** — Safe, parameterized query interface over the FactTable and a well-defined result schema for the agent.
4. **Audit Mode data flow** — How retrieval (vector store + FactTable) returns provenance items and how verification (verified vs. unverifiable) is determined.

This spec defines extractor behavior, schemas, persisted paths, interfaces, and audit data flow. It does not prescribe implementation language or code.

---

## 2. FactTable Extractor Behavior

The FactTable extractor consumes **LDUs** (from Stage 3) and inserts **facts** into the SQLite FactTable. It runs as a post-chunking step (or separate pipeline stage) and is the sole writer of the FactTable.

### 2.1 What qualifies as a "fact"

A **fact** is an atomic, structured assertion that can be expressed as a (subject, quantity, value, context) tuple and that originates from a specific, citable location in a document. The following qualify as facts for extraction:

| Source | Qualifies when | Example |
|--------|----------------|---------|
| **Table LDU** | A cell (or header–cell pair) expresses a measurable quantity with a value and optional unit/period. | Revenue row: entity="Company X", metric="revenue", value="4.2B", unit="USD", period="Q3 2024". |
| **Table LDU** | Header row defines dimensions (e.g. period, category); data rows define entity + metric + value. | Financial statement table: each numeric cell → one fact with entity from row/column context. |
| **Narrative LDU** | A sentence or phrase explicitly states a number with a clear subject and (optionally) period/unit. | "Revenue for the quarter was $4.2B" → entity (from context), metric="revenue", value="4.2B", unit="USD", period=inferred. |
| **List LDU** | A list item is a numbered or bulleted fact (e.g. "3. Net income: 120M"). | Entity/metric/value parsed from list item; period/section from parent_section. |

**Excluded:** Free-form prose with no clear metric/value, captions that only describe a figure (no number), and content that cannot be tied to a single LDU or cell for provenance. When in doubt, the extractor may omit marginal cases to avoid low-quality facts; configurability (e.g. confidence threshold) is recommended.

### 2.2 Mapping to entity / value / unit / period / category_path

Each extracted fact must be mapped to the schema fields as follows:

| Field | Meaning | Mapping rule |
|-------|---------|--------------|
| **entity** | The subject of the fact (who or what the fact is about). | From table row header, section title, document context, or narrative subject. E.g. "Commercial Bank of Ethiopia", "Consolidated Revenue", "Tax Expenditure". Normalize for consistency (e.g. trim, canonicalize casing if configurable). |
| **metric** | The measured quantity or type of fact. | From table column header, explicit noun (e.g. "revenue", "net_income", "total_assets"), or normalized keyword. Use a stable vocabulary where possible (config or ontology). |
| **value** | The numeric or string value of the fact. | Raw cell value or extracted number; may be stored as string to preserve "4.2B" vs "4200000000". Normalization (e.g. to float) is implementation-defined; the spec allows string or numeric column type. |
| **unit** | Unit of measure. | From cell suffix (e.g. "ETB", "%"), column header, or document default. Null if not stated. |
| **period** | Time or reporting period. | From column header (e.g. "Q3 2024"), row label, or narrative phrase ("for the quarter"). Null if not stated. |
| **category_path** | Hierarchical category for grouping/filtering. | Optional. From table structure (e.g. "Income Statement" → "Revenue" → "Interest Income") or section hierarchy (parent_section). Stored as JSON array or delimited string; implementation-defined. |

**Provenance:** Every fact must have a **source_reference** that points to the originating LDU (and ideally page, bbox, content_hash). See §3 for storage; the extractor must set `source_reference` so that it is resolvable to at least `document_id` and `page_number`, and preferably to `ldu_id`, `bounding_box`, and `content_hash` for Citation building.

### 2.3 Extraction flow and scope

- **Input:** List of LDUs (typically for one document, or a batch). DocumentProfile (e.g. domain_hint) may be used to enable/disable or scope extraction (e.g. only financial documents).
- **Process:** For each LDU with `chunk_type` in `table` (and optionally `paragraph` or `list`), run extraction (LLM-based, rule-based table parsing, or hybrid). Emit one or more fact records; set entity, metric, value, unit, period, category_path, document_id, source_reference.
- **Output:** Insert rows into the FactTable. No duplicate key is defined beyond (document_id, entity, metric, period, value) or similar; idempotency (e.g. upsert by source_reference) is implementation-defined.
- **Configurability:** Which documents to run on (e.g. domain_hint=financial), which metrics to extract, confidence threshold, and model/prompt for LLM extraction should be config-driven.

---

## 3. SQLite Schema (FactTable + indexes)

The FactTable is stored in a single SQLite database. One database per refinery instance (or per corpus) is typical; the path is configurable.

### 3.1 Canonical path

- **Path:** `.refinery/fact_table.db` (or equivalent under a configurable base directory, e.g. `data_dir/fact_table.db`). One file per Refinery deployment; all documents’ facts may live in the same DB, distinguished by `document_id`.

### 3.2 Table: `facts`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| **id** | INTEGER | PRIMARY KEY AUTOINCREMENT | Surrogate key. |
| **document_id** | TEXT | NOT NULL | Document from which the fact was extracted. |
| **entity** | TEXT | NOT NULL | Subject of the fact. |
| **metric** | TEXT | NOT NULL | Measured quantity (e.g. revenue, total_assets). |
| **value** | TEXT or REAL | NOT NULL | Value; TEXT allows "4.2B", REAL for numeric-only. |
| **unit** | TEXT | NULL allowed | Unit of measure (e.g. USD, ETB, %). |
| **period** | TEXT | NULL allowed | Time period (e.g. Q3 2024, FY 2023). |
| **category_path** | TEXT | NULL allowed | JSON array or delimited path (e.g. ["Income Statement","Revenue"]). |
| **source_reference** | TEXT | NOT NULL | Provenance: resolvable to page and ideally ldu_id, bbox, content_hash. E.g. `page:42`, `page:42,ldu:ldu_015`, or JSON. |
| **source_page** | INTEGER | NULL allowed | Denormalized 1-based page for fast filtering; populated from source_reference when possible. |
| **created_at** | TEXT | NULL allowed | ISO 8601 timestamp of insert (optional). |

**Invariant:** `source_reference` must never be null. It must be resolvable to at least (document_id, page_number) for Citation building; see [06 – Query Agent & Provenance](06-query-agent-and-provenance-spec.md) §4.

### 3.3 Indexes

Recommended indexes to support `structured_query` and audit flows:

| Index | Columns | Purpose |
|-------|---------|---------|
| **idx_facts_document_id** | (document_id) | Filter by document (e.g. document_ids in query). |
| **idx_facts_metric_period** | (metric, period) | Common filter: "revenue Q3 2024". |
| **idx_facts_entity_metric** | (entity, metric) | Lookup by entity and metric. |
| **idx_facts_source_page** | (document_id, source_page) | Resolve provenance by page when source_reference is parsed. |

Composite indexes (e.g. document_id + metric + period) may be added based on query patterns. The spec requires at least document_id and (metric, period) to be efficiently filterable.

---

## 4. Vector Store: ChromaDB Interface and Persisted Paths

The Refinery uses **ChromaDB** as the vector store for LDU embeddings. The Query Agent’s `semantic_search` tool queries this store.

### 4.1 Choice of ChromaDB

- **Rationale:** ChromaDB is local, free-tier-friendly, supports metadata filtering (document_id, page_refs, ldu_id, parent_section), and persists to disk. It aligns with the Refinery Guide and Phase 3/4 tasks.
- **Alternatives:** FAISS or other in-memory/on-disk stores are acceptable if they meet the interface and metadata requirements below; this spec defines behavior with ChromaDB as the reference implementation.

### 4.2 Persisted path and collection

- **Path:** `.refinery/vector_store/` (or configurable base, e.g. `data_dir/vector_store/`). ChromaDB typically stores its files (SQLite + embeddings) under this directory. One persistent client/instance per Refinery deployment.
- **Collection:** One collection for LDU embeddings (e.g. `ldu_chunks` or configurable name). All documents’ LDUs may live in the same collection, with `document_id` (and optionally `ldu_id`, `page_refs`, `parent_section`) as metadata for filtering.

### 4.3 Interface (contract)

The vector store component must support the following operations. Exact function names are implementation-defined; the contract is the behavior.

| Operation | Inputs | Output | Notes |
|-----------|--------|--------|-------|
| **Ingest LDUs** | List of LDU (each with id, document_id, content, page_refs, bounding_boxes, parent_section, content_hash, chunk_type). | — | Compute embedding from LDU content (or designated text field). Store with metadata: document_id, ldu_id, page_refs (or first page), parent_section, content_hash. Add or upsert by ldu_id so re-runs are idempotent. |
| **Search** | query_text: str; top_k: int; optional document_ids: list[str]; optional section_constraint: (ldu_ids or page range or section ids). | List of results. Each result: content, document_id, ldu_id, page_refs, bounding_boxes (or first bbox), content_hash, parent_section (and any metadata needed for Citation). Results ordered by similarity (distance) descending. | If section_constraint is provided, filter by metadata (e.g. ldu_id in set, or page in range) before or after vector search. Embedding model must be consistent between ingest and search. |
| **Delete by document_id** (optional) | document_id: str | — | Remove all entries for that document (e.g. for re-indexing). Not required for minimal spec but useful for pipeline updates. |

**Metadata requirements:** Stored metadata must include at least: `document_id`, `ldu_id`, and enough to derive `page_refs` and `bounding_boxes` (or first page and first bbox) so that each search hit can be turned into a Citation (document_name, page_number, bbox, content_hash) per spec 06 §4.

### 4.4 LDU ingestion flow

1. **Input:** List of LDUs from Stage 3 (Chunking Engine), after ChunkValidator.
2. **Per LDU:** Compute embedding from `content` (or normalized text). Store in ChromaDB with id = ldu_id (or stable id), metadata = { document_id, ldu_id, page_refs (serialized), bounding_boxes or first bbox, parent_section, content_hash, chunk_type }.
3. **Idempotency:** Use ldu_id as ChromaDB document id (or equivalent) so re-ingesting the same LDU updates rather than duplicates.
4. **Config:** Embedding model, embedding dimension, and persist path are configurable.

---

## 5. structured_query Tool Contract

The **structured_query** tool is one of the three agent tools. It executes read-only queries over the FactTable and returns a result schema that the agent (and provenance layer) can consume.

### 5.1 Tool contract (inputs)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| **query** | string | Yes | Natural-language question or parameterized intent (e.g. "revenue in Q3 2024", "total tax expenditure FY 2020"). The implementation maps this to SQL or a safe query. |
| **document_ids** | list[string] | No | If provided, restrict results to facts with document_id in this list. |

No other parameters are required. The tool is invoked by the agent; the agent may pass document_ids from a prior step (e.g. from pageindex_navigate).

### 5.2 Safe parameterization and SQL

- **No raw user SQL:** The tool must **not** accept arbitrary SQL from the user or from an untrusted LLM output. User input is natural language or structured parameters (e.g. metric, period, entity).
- **Safe execution:** Queries against the FactTable must be generated internally via:
  - **Parameterized queries** — e.g. `SELECT ... FROM facts WHERE document_id = ? AND metric LIKE ? AND period = ?`, with parameters bound from parsed query or agent-provided values; or
  - **Template-based SQL** — Predefined templates with placeholders (e.g. by metric, by period, by entity); placeholders are sanitized (e.g. string escape, no subqueries); or
  - **LLM-generated SQL with validation** — If the implementation uses an LLM to generate SQL, the SQL must be validated (e.g. allowlist of tables/columns, read-only, no DDL/DML) and executed with bound parameters only. No concatenation of user input into SQL.
- **Read-only:** Only SELECT is allowed. No INSERT, UPDATE, DELETE, or schema changes.

### 5.3 Result schema (output)

Every successful call returns a **list of rows**. Each row is a fact record with at least the following fields so the agent can format an answer and the provenance layer can build Citations:

| Field | Type | Description |
|-------|------|-------------|
| **document_id** | string | Document from which the fact was extracted. |
| **entity** | string | Subject of the fact. |
| **metric** | string | Measured quantity. |
| **value** | string or number | The value. |
| **unit** | string or null | Unit of measure. |
| **period** | string or null | Time period. |
| **category_path** | list or string or null | Hierarchical category if stored. |
| **source_reference** | string | Provenance string; must be resolvable to at least document_id and page_number for Citation. |

When no rows match, the tool returns an **empty list** (not an error). On SQL or execution errors (e.g. DB unavailable), the tool returns an error to the agent (e.g. empty list plus logged error, or raised exception per implementation); the agent then falls back to semantic_search per spec 06.

---

## 6. Audit Mode Data Flow: Retrieval → Provenance → Verification

Audit mode answers: "Does the document (or corpus) support this claim?" The data layer supplies the **retrieval results** and **provenance items**; the agent (or a dedicated audit path) **evaluates** support and sets verification status. This section defines the data flow and how verification is determined from data.

### 6.1 Data sources for audit

For a given **claim**:

1. **FactTable (structured_query)** — Run structured_query with the claim (or parsed entity/metric/period). Returns zero or more fact rows, each with source_reference and document_id, entity, metric, value, period.
2. **Vector store (semantic_search)** — Run semantic_search with the claim (or a reformulation). Returns zero or more LDUs, each with document_id, ldu_id, page_refs, bounding_boxes, content_hash, content.

No other data sources are required for audit. PageIndex may be used optionally to narrow semantic_search (e.g. by topic) but is not required for the audit data flow.

### 6.2 From retrieval to provenance items

- **From FactTable rows:** Each returned row has `source_reference`. Resolve source_reference to at least (document_id, page_number). If source_reference encodes ldu_id or bbox/content_hash (e.g. from extraction), resolve to (document_id, page_number, bbox, content_hash). Build one **ProvenanceItem (Citation)** per row (or per distinct source_reference): document_id, document_name (from document registry), page_number, bbox (if available), content_hash (if available), snippet (optional, e.g. from original cell text). See spec 06 §4 and spec 07 §7.1.
- **From semantic_search LDUs:** Each returned LDU has document_id, ldu_id, page_refs, bounding_boxes, content_hash, content. Build one **ProvenanceItem** per LDU: document_id, document_name, page_number (e.g. first of page_refs), bbox (e.g. first of bounding_boxes), content_hash, snippet (e.g. truncate content). See spec 06 §4.

**Invariant:** Provenance items are built **only** from these retrieval results. No item may be invented or filled with placeholder page/bbox when the source does not provide it. For FactTable-only rows without bbox/content_hash in source_reference, bbox and content_hash may be null in the Citation.

### 6.3 How verification is determined

**Verification** is a decision over the **retrieval results** and the **claim**:

1. **Evaluate FactTable results:** For each fact row, check whether (entity, metric, value, unit, period) support the claim. Support means: value matches (or is semantically consistent, e.g. "4.2B" vs "approximately $4.2 billion"); metric and period align with the claim. If at least one row supports the claim → **supported by FactTable**; collect the corresponding provenance items for those rows.
2. **Evaluate semantic_search results:** For each retrieved LDU, use the content (and optionally an LLM or rules) to decide whether the text supports the claim. If at least one LDU supports the claim → **supported by LDUs**; collect the corresponding provenance items for those LDUs.
3. **Combined decision:**
   - If **any** source (FactTable or LDU) supports the claim → **Verified**. Return verification_status = `verified` and a ProvenanceChain with **at least one** citation (the provenance items from the supporting source(s)). Never return verified with an empty citation list.
   - If **no** source supports the claim (FactTable returned nothing or no matching value; semantic_search returned nothing or no supporting content) → **Unverifiable**. Return verification_status = `unverifiable` and a ProvenanceChain with **no** citations (empty list). Response text must state that the claim could not be verified (e.g. "No supporting source was found"). Never invent a citation or a page number/bbox.

**Data flow summary:**

- **Retrieval** (data layer): structured_query(claim) → fact rows; semantic_search(claim) → LDUs.
- **Provenance items** (data layer / agent): fact rows → Citations (via source_reference resolution); LDUs → Citations (via LDU fields).
- **Evaluation** (agent / audit module): Compare claim to fact rows and LDU content; decide supported vs not supported.
- **Output** (agent): If supported → ProvenanceChain with citations + verification_status = verified. If not supported → ProvenanceChain with empty citations + verification_status = unverifiable; no fake citation.

This ensures Audit Mode never fakes verification: verification is determined solely from actual retrieval results and explicit comparison to the claim.

---

## 7. Summary Table

| Component | Persisted path | Interface / contract |
|-----------|----------------|------------------------|
| **FactTable** | `.refinery/fact_table.db` | SQLite; facts table + indexes; source_reference NOT NULL. |
| **Fact extractor** | — | Consumes LDUs; outputs facts with entity, metric, value, unit, period, category_path, source_reference. |
| **Vector store** | `.refinery/vector_store/` | ChromaDB; ingest LDUs (embedding + metadata); search with optional document_ids and section_constraint; return LDU-like results for Citation. |
| **structured_query** | Reads FactTable | Input: query, optional document_ids. Safe parameterized SQL only. Output: list of rows (document_id, entity, metric, value, unit, period, source_reference, ...). |
| **Audit data flow** | — | Retrieval (FactTable + vector store) → provenance items from rows/LDUs only → evaluation (support vs not) → verified (with citations) or unverifiable (no citations). |

---

**Version:** 1.0  
**Spec status:** Spec only; implementation-agnostic. Defines data layer for Phase 4 and Query Agent.
