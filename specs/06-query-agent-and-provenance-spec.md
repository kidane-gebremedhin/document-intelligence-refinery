# Spec: Stage 5 – Query Interface Agent & Provenance Layer

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Upstream:** [04 – Semantic Chunking Engine & LDUs](04-semantic-chunking-and-ldu-spec.md), [05 – PageIndex Builder](05-pageindex-builder-spec.md)  
**Constitution alignment:** Spatial provenance non-negotiable; PageIndex-first retrieval; typed Pydantic contracts; every answer carries a ProvenanceChain; audit mode for claim verification.

---

## 1. Purpose

Stage 5 is the **user-facing surface** of the Document Intelligence Refinery. It is the single entry point for:

- **Question answering** — Natural-language queries over the corpus (e.g., "What was revenue in Q3 2024?", "What are the main risk factors?").
- **Navigation** — Locating information by structure (PageIndex traversal) rather than by brute-force search.
- **Verification** — Audit mode: given a claim, the system confirms it with a citation or flags it as unverifiable.

The Refinery Guide states that the Query Interface Agent is "the front-end of the refinery"—a **LangGraph agent with exactly three tools**. Every answer must include a **ProvenanceChain** with citations carrying document name, page number, bounding box, and content_hash. This stage makes the upstream pipeline (triage, extraction, chunking, indexing) **useful** and **auditable**. Without it, the refinery produces data but no way to query or trust it. **Audit mode** ensures claim verification yields either citations or an explicit "unverifiable" flag—never fake verification.

---

## 2. Inputs & Dependencies

The Query Interface Agent **does not ingest raw documents**. It operates exclusively on the outputs of Stages 1–4 and the FactTable extractor. It is a read-only consumer of pre-built artifacts.

### 2.1 Required dependencies

| Dependency | Source | Role |
|------------|--------|------|
| **PageIndex trees** | Stage 4 (PageIndex Builder) | Hierarchical navigation. Stored per document (e.g. `.refinery/pageindex/{doc_id}.json`). Provides section titles, page ranges, summaries, key_entities, data_types_present. Used by `pageindex_navigate`. |
| **Vector store** | Post–Stage 3 (LDU ingestion) | Embeddings of LDUs for semantic search. Implementation: ChromaDB. Used by `semantic_search`. |
| **LDUs** | Stage 3 (Semantic Chunking Engine) | Logical Document Units with content, page_refs, bounding_box, content_hash. Must be ingested into the vector store with metadata (document_id, page_refs, ldu_id, etc.) so retrieved chunks can be mapped back to provenance. |
| **FactTable (SQLite)** | FactTable extractor | Structured key-value facts for numerical/financial documents. Columns: entity, metric, value, unit, period, source_reference. Used by `structured_query`. |

### 2.2 Optional / derived

| Dependency | Description |
|------------|-------------|
| **DocumentProfile** | From Stage 1. May be used to route queries (e.g., domain_hint=financial → prefer structured_query for numerical questions). |
| **Extraction ledger** | For audit context (e.g., which strategy extracted the document; confidence). Not required for core query flow. |
| **Document metadata** | Mapping from document_id to human-readable document name (e.g., filename). Required for ProvenanceChain `document_name`. |

### 2.3 Pre-conditions

- At least one document has been processed through Stages 1–4; PageIndex and vector store are populated.
- FactTable is populated for documents that support it (financial, numerical). If absent, `structured_query` is unavailable or returns empty.
- Document names are resolvable from document_id for provenance display.

---

## 3. LangGraph Agent Definition & Tools

The Query Interface Agent is implemented as a **LangGraph agent** with **exactly three tools**. No other tools are part of the Refinery query interface; the agent chooses which of these three to call (and in what order) based on the user query. Tool semantics are defined below; graph structure (nodes, edges, conditional routing) is implementation-defined, but the **tool set is fixed**.

| # | Tool | Purpose |
|---|------|---------|
| 1 | **pageindex_navigate** | Traverse PageIndex by topic; return top-N sections before vector search. |
| 2 | **semantic_search** | Retrieve LDUs by semantic similarity (RAG retrieval). |
| 3 | **structured_query** | Execute query over FactTable (SQLite) for numerical/factual lookups. |

The agent may call one or more tools per query (e.g. pageindex_navigate then semantic_search). It must **not** expose or use any tool other than these three for answering user questions or audit claims.

### 3.1 pageindex_navigate

**Purpose:** Traverse the PageIndex to find sections relevant to a topic before performing vector search. Enables PageIndex-first retrieval.

**Inputs:**
- `topic` — Natural language string (e.g., "capital expenditure projections", "auditor's opinion").
- `document_id` (optional) — If specified, search only that document's PageIndex. If omitted, search across all documents.
- `top_n` (optional) — Number of sections to return (default: 3).

**Behavior:**
- Score each section in the PageIndex by relevance to `topic` using title, summary, key_entities, data_types_present.
- Return the top-N sections with: section id, title, page_start, page_end, summary, ldu_ids (or equivalent).
- No vector search is performed. Output is used to **restrict** the scope of subsequent `semantic_search` (e.g., only search LDUs within those sections).

**When used:**
- Queries that benefit from structural context: "Where is the auditor's opinion?", "What section discusses risk factors?", "Show me the capital expenditure section."
- Long documents where naive vector search is noisy. The agent should prefer PageIndex-first when the query implies a specific document region.

### 3.2 semantic_search

**Purpose:** Retrieve LDUs by semantic similarity to the query. Standard RAG retrieval.

**Inputs:**
- `query` — Natural language string (the user question or a reformulation).
- `document_ids` (optional) — Restrict to specific documents. If provided by `pageindex_navigate` output (section → document), only those documents are searched.
- `section_constraint` (optional) — Page ranges or section ids from `pageindex_navigate`. When present, filter LDUs to those within the given sections before or after embedding search.
- `top_k` (optional) — Number of chunks to retrieve (default: e.g., 5–10).

**Behavior:**
- Embed the query (or reformulated query).
- Search the vector store. If `section_constraint` is provided, either: (a) pre-filter LDUs by section/page range, then embed search, or (b) post-filter top-N results to those in the constraint.
- Return ranked LDUs with content, document_id, ldu_id, page_refs, bounding_box, content_hash, parent_section.

**When used:**
- Always used for question answering when context is needed. May be preceded by `pageindex_navigate` (PageIndex-first flow) or used alone (naive flow) for short documents or broad queries.
- Queries that require reading specific text: "What does the report say about digital transformation?", "Summarize the key findings."

### 3.3 structured_query

**Purpose:** Execute SQL (or equivalent) over the FactTable for precise numerical or factual lookups.

**Inputs:**
- `query` — Natural language or a parameterized query (e.g., "revenue in Q3 2024", "total tax expenditure FY 2020").
- `document_ids` (optional) — Restrict to specific documents.

**Behavior:**
- Map the natural-language query to a FactTable query (e.g., via query decomposition, LLM-generated SQL, or predefined templates).
- Execute against SQLite. Return rows with entity, metric, value, unit, period, and `source_reference` (for provenance).
- Each returned fact must include provenance: document_id, page, and ideally bbox or content_hash from the source LDU.

**When used:**
- Queries that ask for specific numbers: "What was revenue in Q3 2024?", "What is the total tax expenditure for 2020?", "List all capital expenditure figures."
- Domain_hint=financial or table-heavy documents. If FactTable is empty, the tool returns no results and the agent falls back to `semantic_search`.

### 3.4 Tool orchestration (within the three tools)

The agent orchestrates the **same three tools** based on query intent:
- **Navigational** ("Where is X?") → `pageindex_navigate` possibly followed by `semantic_search` if the user needs the actual content.
- **Numerical / factual** ("What was Y in Z?") → `structured_query` first; if empty, `semantic_search`.
- **Synthesis / narrative** ("Summarize X", "What does the report say about Y?") → `pageindex_navigate` + `semantic_search`, or `semantic_search` alone for broad queries.
- **Hybrid** — The agent may call multiple tools and combine results (e.g., PageIndex for scope, semantic search for chunks, structured query for a specific number).

---

## 4. ProvenanceChain Schema

**Every answer** from the Query Interface Agent must include a **ProvenanceChain**: a list of source citations so the user can verify the answer against the original document. The Refinery Guide requires: "Every answer must include provenance: the document name, page number, and bounding box of the source." The constitution states: spatial provenance is non-negotiable. Each citation must carry at least **document_name**, **page_number**, **bounding_box**, and **content_hash** (for LDU-backed sources).

### 4.1 ProvenanceChain (top-level)

| Field | Type | Description |
|-------|------|-------------|
| **citations** | list of Citation | One citation per distinct source (LDU or fact row). Ordered by relevance or appearance in the answer. For audit mode: empty when claim is unverifiable. |
| **verification_status** | enum (optional) | `verified` \| `partial` \| `unverifiable`. Used in audit mode: verified only when citations exist; unverifiable when no supporting source found. See §7, §8. |

### 4.2 Citation (single source) — required fields for every answer

Every citation in a ProvenanceChain must include the following so that answers are auditable:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **document_name** | string | Yes | Human-readable document identifier (e.g., filename, report title). Resolved from document_id. |
| **document_id** | string | Yes | Stable document identifier for programmatic reference. |
| **page_number** | integer | Yes | 1-based page number where the cited content appears. |
| **bounding_box** | object | Yes* | Spatial coordinates: `{x0, top, x1, bottom}` or equivalent. Enables "click to locate" in a PDF viewer. *For LDU-backed citations, required; for FactTable-only citations, may be null if not stored in source_reference. |
| **content_hash** | string | Yes* | Stable hash of the source content (from LDU). Required for LDU-backed citations; for FactTable, optional if source_reference does not resolve to an LDU. |
| **snippet** | string (optional) | No | Short excerpt of the cited content (e.g., first 100–200 chars). |
| **ldu_id** | string (optional) | No | LDU identifier for traceability. |
| **chunk_type** | enum (optional) | No | `paragraph` \| `table` \| `figure` \| etc. |

**Minimum required per citation (LDU-backed):** `document_name`, `document_id`, `page_number`, `bounding_box`, `content_hash`. For FactTable-only: at least `document_name`, `document_id`, `page_number`; `bounding_box` and `content_hash` when resolvable from source_reference.

### 4.3 Invariants

- **Every answer** must include a ProvenanceChain. When the agent has no sources (e.g. no retrieval results), the chain may have empty citations and a clear "no sources" or unverifiable signal—but the chain is still present.
- Every citation must have the required fields above. No citation with missing required fields (for its source type) may be emitted.
- The ProvenanceChain must be **actionable**: a user with the original PDF can open the cited page and locate the content using the bounding box (when bbox is present).

---

## 5. FactTable Extraction Requirements

The FactTable is a SQLite-backed store of structured key-value facts extracted from numerical/financial documents. It enables precise queries without vector search. The Query Agent uses it via `structured_query`.

### 5.1 Minimal schema

| Column | Type | Description |
|--------|------|-------------|
| **id** | integer (PK) | Auto-increment primary key. |
| **document_id** | string | Document from which the fact was extracted. |
| **entity** | string | The subject (e.g., "Commercial Bank of Ethiopia", "Revenue", "Tax Expenditure"). |
| **metric** | string | The measured quantity (e.g., "revenue", "total_assets", "net_income"). |
| **value** | string or numeric | The value (e.g., "4.2", "4.2B", "4200000000"). Normalization (e.g., numeric vs. string) is implementation-defined. |
| **unit** | string (optional) | Unit of measure (e.g., "ETB", "USD", "%"). |
| **period** | string (optional) | Time period (e.g., "Q3 2024", "FY 2023", "June 30, 2024"). |
| **source_reference** | string | Provenance link: page number, LDU id, or structured reference (e.g., `page:42,ldu:ldu_015`). Must be resolvable to a Citation. |

### 5.2 Extraction scope

- **Target documents:** Financial reports, tax reports, audit reports (domain_hint=financial or document structure suggests tables with numerical data).
- **Source:** Table LDUs and, optionally, narrative paragraphs that contain key figures (e.g., "Revenue for the quarter was $4.2B").
- **Extraction method:** LLM-based extraction, rule-based parsing of table rows, or hybrid. Implementation choice. Output must conform to the schema.

### 5.3 Invariants

- Every fact must have `source_reference` so that `structured_query` results can be turned into ProvenanceChain citations.
- Facts from the same table row may share a source_reference (one citation per table region) or have row-level references; spec leaves granularity to implementation.

---

## 6. Query Flows (Happy Paths)

### 6.1 "What was revenue in Q3 2024?"

**Flow:**
1. Agent interprets query as numerical/factual → calls `structured_query` with query "revenue Q3 2024".
2. FactTable returns matching rows (entity, metric, value, unit, period, source_reference).
3. Agent formats the answer (e.g., "Revenue in Q3 2024 was $4.2B.").
4. Agent resolves `source_reference` to Citation(s): document_name, page_number, bbox, content_hash.
5. Answer + ProvenanceChain returned to user.

**Fallback:** If FactTable returns empty (no matching period or metric), agent calls `semantic_search` with query "revenue Q3 2024", retrieves relevant LDUs, generates answer from chunks, and attaches ProvenanceChain from those LDUs.

---

### 6.2 "Show me the auditor's opinion"

**Flow:**
1. Agent interprets query as navigational / section-specific → calls `pageindex_navigate` with topic "auditor's opinion".
2. PageIndex returns top sections (e.g., "Independent Auditor's Report", pages 5–7).
3. Agent calls `semantic_search` with `section_constraint` = those sections (or document + page range).
4. Retrieves LDUs containing the auditor's opinion text.
5. Agent returns the content (or a summary) + ProvenanceChain from the retrieved LDUs.
6. User can open the PDF to the cited page(s) and read the full opinion.

---

### 6.3 "What are the capital expenditure projections for Q3?"

**Flow:** (Refinery Guide critical use case)
1. Agent calls `pageindex_navigate` with topic "capital expenditure projections".
2. PageIndex returns sections (e.g., "5. Capital Budget", "6. Projections").
3. Agent calls `semantic_search` with query "capital expenditure projections Q3" and `section_constraint` from step 1.
4. Alternatively or additionally, `structured_query` if FactTable has capital expenditure figures with period "Q3".
5. Agent synthesizes answer from retrieved chunks and/or fact rows.
6. ProvenanceChain includes all cited sources.

---

### 6.4 "Summarize the key findings of the report"

**Flow:**
1. Agent may call `pageindex_navigate` with topic "key findings" to locate relevant sections.
2. Agent calls `semantic_search` with query "key findings" (with optional section constraint).
3. Agent (or an LLM) summarizes the retrieved content.
4. ProvenanceChain cites the LDUs used for the summary. Multiple citations expected.

---

## 7. Audit Mode Behavior

**Audit mode** answers: "Does the document support this claim?" Given a user-supplied claim, the system performs **claim verification**. The outcome is **exactly one** of:

1. **Verified** — At least one supporting source was found. Response includes a ProvenanceChain with one or more citations (document_name, page_number, bbox, content_hash). `verification_status` = `verified` (or equivalent).
2. **Unverifiable** — No supporting source was found. Response includes an explicit **"unverifiable"** flag and **no citations** (or an empty ProvenanceChain). No page number, bbox, or document_name may be invented. `verification_status` = `unverifiable`.

**Audit mode must never fake verification.** The system must never return a citation when no actual source supports the claim, and must never mark a claim as verified without at least one real citation. When in doubt or when no evidence is found, the only correct outcome is **unverifiable** with a clear message.

### 7.1 Input

- **claim** — The statement to verify (e.g., "Revenue was $4.2B in Q3 2024").
- **document_id** (optional) — If specified, search only that document. If omitted, search corpus-wide.

### 7.2 Behavior

1. **Parse the claim** — Extract key entities and values (e.g., metric=revenue, value=4.2B, period=Q3 2024).
2. **Query FactTable** — If the claim is numerical, run `structured_query` for matching facts. Compare returned values to the claim.
3. **Query semantic search** — Run `semantic_search` with the claim (or a reformulation) to find LDUs that might support or contradict it.
4. **Evaluate** — Determine if any retrieved content supports the claim. Criteria: value matches (or is consistent), metric matches, period matches. Use LLM or rules for semantic match (e.g., "approximately $4.2 billion" supports "revenue was $4.2B").
5. **Output (strict):**
   - **Verified:** Return confirmation + ProvenanceChain with **at least one** supporting citation (document_name, page_number, bounding_box, content_hash). Set verification_status to `verified`. Citations must come only from the retrieved LDUs or FactTable rows that were evaluated as supporting.
   - **Unverifiable:** Return explicit "unverifiable" signal. ProvenanceChain has **no citations** (empty list). Response text: e.g. "The claim could not be verified. No supporting source was found in the corpus." Do **not** invent a citation, page number, or bbox. Set verification_status to `unverifiable`.

### 7.3 Invariants (Audit Mode)

- **Either citations or unverifiable** — Every claim verification result is either (a) verified with one or more citations, or (b) unverifiable with no citations and an explicit unverifiable flag. There is no third outcome (e.g. "verified" with no citation is forbidden).
- **Never fake verification** — The system must never return a citation for a claim it cannot support. It must never hallucinate page number, bbox, document_name, or content_hash. Citations are only from actual retrieved LDUs or FactTable rows that were evaluated as supporting the claim.
- **Clear distinction** — The response must clearly distinguish verified (with citation(s)) vs. unverifiable (no citation, explicit flag).

---

## 8. Error Handling & "Unverifiable" Responses

### 8.1 When to return "Unverifiable"

| Condition | Response |
|-----------|----------|
| **No supporting source found** | "The claim could not be verified. No supporting source was found in the corpus." |
| **Ambiguous or conflicting sources** | "The claim could not be verified. Multiple sources with conflicting information were found." Optionally list the conflicts. |
| **Source found but does not match claim** | "The claim could not be verified. The closest relevant source states [X], which does not support the claim." |
| **Empty corpus or document not indexed** | "The claim could not be verified. The document (or corpus) has not been indexed." |

### 8.2 Error handling (non-audit)

| Failure | Behavior |
|---------|----------|
| **Vector store unavailable** | Return error to user: "Semantic search is temporarily unavailable." Log. Do not return an answer without retrieval. |
| **PageIndex missing** | Fall back to naive `semantic_search` (no section constraint). Log. |
| **FactTable empty or query failed** | Fall back to `semantic_search`. Do not block the answer. |
| **LLM timeout / API error** | Return error: "The query could not be completed. Please try again." Log. Retry policy is implementation-defined. |
| **Invalid query (e.g., empty)** | Return validation error: "Please provide a non-empty query." |

### 8.3 Communicating uncertainty

- **Low-confidence retrieval:** If the top retrieved chunks have low similarity scores, the agent may preface the answer with: "Based on the available sources, ..." or "The following answer is based on limited matching content."
- **Partial verification:** If only part of a compound claim is supported, the response should say so: "The revenue figure ($4.2B) is supported [citation], but the period (Q3) could not be confirmed from the same source."
- **No speculation:** The agent must not fill gaps with inferred or hallucinated content. When uncertain, it should say so or return "unverifiable" for the specific sub-claim.

---

## 9. Non-Functional Requirements

### 9.1 Latency

- **Target:** Query response (including retrieval + LLM generation) within a reasonable interactive window (e.g., &lt; 30 seconds for typical queries). Exact SLA is deployment-dependent.
- **Optimization:** PageIndex-first retrieval reduces the number of chunks to embed and rank; use it for long documents. Limit `top_k` for semantic search to avoid large context and slow generation.
- **Timeouts:** Configurable timeouts for vector search, FactTable query, and LLM calls. On timeout, return a clear error rather than hanging.

### 9.2 Robustness

- **Graceful degradation:** If one tool fails (e.g., FactTable unavailable), the agent should fall back to other tools (e.g., semantic_search) when possible. Never crash; return an error or degraded answer with explanation.
- **Empty results:** Handle "no results" from any tool. Do not pass empty context to the LLM and then present an unsupported answer. Either say "No relevant content found" or ask the user to rephrase.
- **Corpus growth:** The system should support adding new documents without restart. Vector store and PageIndex are assumed to be updated by the pipeline; the Query Agent reads the current state.

### 9.3 Traceability

- **Query logging:** Every query (and tool calls) should be logged with: timestamp, query text, tools invoked, documents/sections searched, result count, latency. Enables debugging and retrieval quality analysis.
- **ProvenanceChain audit trail:** ProvenanceChain is part of the response; it may also be logged or stored separately for compliance (e.g., "what sources supported this answer?").
- **Agent trace:** If using LangGraph, the agent's execution trace (nodes visited, tool outputs) should be persistable for debugging. Mirrors Week 1's agent_trace.jsonl concept.

### 9.4 Configurability

- Tool selection heuristics, top_k, top_n, timeouts, and fallback policies should be configurable (config-over-code). No hardcoded thresholds for production tuning.

---

## 10. Open Questions

- **Query routing logic:** Exact rules or model for "when to use structured_query vs. semantic_search" — to be refined with domain testing.
- **Multi-document aggregation:** How to combine and rank results when the corpus spans many documents; how to present multi-document ProvenanceChains.
- **FactTable extraction pipeline:** Whether FactTable extraction is a separate stage or part of post-chunking processing; schema evolution when new metric types are added.
- **Snippet length and format:** Optimal snippet length for Citation; whether to truncate tables or preserve structure in snippet.

---

**Version:** 1.0  
**Spec status:** Ready for implementation; implementation-agnostic but sufficient for Query Agent and provenance layer design.
