# Spec: The Document Intelligence Refinery – System-Level Specification

**Source of truth:** *The Document Intelligence Refinery Guide* (reference-docs).  
**Constitution alignment:** This spec complies with the project constitution (multi-strategy extraction, spatial provenance, document-aware chunking, PageIndex-first retrieval, typed Pydantic contracts, config-over-code).

---

## 1. Problem Statement

Enterprises hold institutional memory in PDFs, scans, slide decks, and spreadsheets. The gap between “we have the document” and “we can query it as structured data” blocks AI deployment and costs billions annually. Three failure modes must be addressed:

- **Structure Collapse.** Traditional OCR flattens two-column layouts, breaks tables, drops headers. Text is present but structure is lost; tables become unparseable strings and reading order is destroyed. Downstream systems cannot reliably interpret the content.

- **Context Poverty.** Naive chunking for RAG severs logical units: a table split across chunks, a figure separated from its caption, a clause cut from its antecedent. Retrieval returns incomplete context; LLMs hallucinate. Token-boundary chunking is a direct cause of untrustworthy answers.

- **Provenance Blindness.** Most pipelines cannot answer “Where in this 400-page report does this number come from?” Without spatial provenance (page + bounding box), extracted data cannot be audited, disputed, or trusted. Compliance and legal use cases require citation to the source location.

Enterprises care because: (1) they need to query documents at scale without manual tagging, (2) they must audit and justify every claim, and (3) they cannot afford “AI said so” without a verifiable trail to the source.

---

## 2. Business Context & Objectives

The refinery is built for **Forward Deployed Engineer (FDE) client engagements**. An FDE has limited time to show value; in enterprise settings that value often starts with making the client’s documents queryable. The objective is a **48-hour pipeline**: deploy a document-intelligence pipeline quickly that works on the client’s actual document mix, with classification-aware extraction, spatial indexing, and provenance preservation.

The system is not a generic PDF reader. It is a **refinery**: heterogeneous documents in, structured, queryable, spatially-indexed knowledge out. Success means: triage → extraction → chunking → indexing → querying, with strategy selection and escalation driven by document profile and confidence, not one-size-fits-all VLM.

---

## 3. In-Scope Functionality

- **Document triage.** Classify each document (origin type, layout complexity, language, domain hint) and assign an estimated extraction cost tier. Output a DocumentProfile that drives strategy selection.

- **Multi-strategy structure extraction.** Three strategies with explicit escalation: (A) fast text where sufficient, (B) layout-aware extraction for multi-column/table-heavy/mixed content, (C) vision-augmented extraction for scanned/handwritten/low-confidence cases. Confidence-gated escalation so bad extractions do not flow downstream.

- **Semantic chunking.** Convert raw extraction into Logical Document Units (LDUs) that respect structure: no table-cell splits, captions with figures, section context preserved. Chunk boundaries are structure-based; token limits apply only after structural boundaries are respected (constitution: document-aware chunking).

- **PageIndex building.** Build a hierarchical navigation structure over each document (section tree with page ranges, key entities, short summaries, data types). Enables “which page(s)?” before vector search (constitution: PageIndex-first retrieval).

- **Query interface with provenance.** Support navigation (PageIndex), semantic search (vector retrieval), and structured query (e.g. SQL over fact tables). Every answer includes provenance: document, page, bounding box (constitution: spatial provenance non-negotiable).

- **Audit trail.** Ledger of extraction decisions (strategy used, confidence, cost estimate) and provenance chain for answers so claims can be verified against the source.

---

## 4. Out-of-Scope Functionality

- **End-user UI or dashboards.** No built-in web UI, admin console, or visualization layer. The system exposes pipeline stages and query interfaces; UIs are built on top by consumers.

- **Full MLOps platform.** No model training, hyperparameter tuning, or experiment tracking. Model choice and routing are configurable; training and lifecycle management are out of scope.

- **Real-time streaming ingestion.** Design is batch-oriented (document in → profile → extract → chunk → index → query). Stream processing and sub-second latency SLAs are not in scope.

- **Generic document authoring or editing.** The refinery ingests and refines; it does not create or edit documents.

- **Horizontal scaling and multi-tenant SaaS.** Architecture is pipeline- and corpus-focused. Scaling and tenancy are deployment concerns, not part of this system spec.

---

## 5. Users & Usage Scenarios

- **Forward Deployed Engineer (FDE).** Onboards a new client corpus: runs triage to see document mix, inspects DocumentProfiles and extraction ledger, tunes extraction rules and thresholds in config (no code change). Delivers a working pipeline in 48 hours and can explain strategy selection and cost tradeoffs to the client.

- **Data engineer.** Integrates the refinery into a data platform: ingests document outputs (JSON schemas, PageIndex trees, vector store, fact tables), runs batch jobs, monitors extraction ledger and cost. Relies on typed contracts (Pydantic) and config-driven thresholds for reproducible, testable pipelines.

- **Analyst / knowledge worker.** Asks natural-language questions over the corpus; receives answers plus provenance (page + bbox). Uses PageIndex navigation for long reports and structured query for numerical/factual lookups. Verifies critical claims via audit mode (citation or “unverifiable”).

---

## 6. High-Level Architecture (5-Stage Pipeline)

The refinery is a **five-stage pipeline**. Each stage has typed inputs and outputs; data contracts are Pydantic models (constitution). Strategy routing and thresholds are config-driven (constitution).

| Stage | Name | Purpose | Key outputs |
|-------|------|---------|-------------|
| 1 | **Triage Agent** | Classify document so downstream stages choose strategy. | DocumentProfile (origin_type, layout_complexity, domain_hint, estimated_extraction_cost). |
| 2 | **Structure Extraction Layer** | Multi-strategy extraction with confidence-gated escalation. | Normalized extracted content (text blocks, tables, figures with bbox + page). Extraction ledger entries. |
| 3 | **Semantic Chunking Engine** | Turn extraction into RAG-ready LDUs without breaking structure. | List of LDUs (content, chunk_type, page_refs, bbox, parent_section, content_hash). |
| 4 | **PageIndex Builder** | Hierarchical navigation over the document. | PageIndex tree (sections, page ranges, summaries, key entities, data types). |
| 5 | **Query Interface Agent** | Answer questions using PageIndex, vector search, and structured query; attach provenance. | Answers with ProvenanceChain (document, page, bbox, content_hash); optional fact tables and audit trail. |

**Key data artifacts:** DocumentProfile per document; normalized ExtractedDocument (unified across strategies); LDUs; PageIndex tree; vector store of LDUs; fact tables (e.g. SQLite for numerical/financial); extraction ledger; provenance chain on every answer.

**Flow:** Triage → Extraction (with escalation guard) → Chunking (structure-respecting) → PageIndex build → Query (PageIndex-first, then semantic/structured as needed). All facts carry bbox + page.

---

## 7. Inputs & Outputs

**Inputs — document classes (target corpus):**

- **Class A — Annual financial report (native digital PDF).** Multi-column layouts, embedded financial tables, footnotes, cross-references. Validates layout-aware extraction and table fidelity.

- **Class B — Scanned government/legal (image-based PDF).** No character stream; pure scan. Validates escalation to vision-augmented extraction and OCR quality.

- **Class C — Technical assessment (mixed: text, tables, structured findings).** Mixed layout, narrative + tables + hierarchical sections. Validates strategy routing and section-aware chunking.

- **Class D — Structured data report (table-heavy, numerical).** Multi-year fiscal tables, numerical precision, category hierarchies. Validates table extraction and fact-table population.

**Outputs:**

- **Structured JSON schemas.** DocumentProfile, ExtractedDocument (or equivalent), LDU, PageIndex node, ProvenanceChain — all as typed, testable Pydantic models.

- **PageIndex tree.** Per-document hierarchical navigation (sections, page_start/page_end, summaries, key_entities, data_types_present).

- **Vector store.** RAG-ready embeddings of LDUs for semantic search, used after PageIndex when needed.

- **Fact tables.** SQL-queryable key-value or tabular facts (e.g. revenue, dates) for numerical/domain-specific querying.

- **Audit trail.** Extraction ledger (strategy, confidence, cost per document); ProvenanceChain on every query answer for verification.

---

## 8. Quality Attributes (Non-Functional Requirements)

- **Accuracy.** Extraction fidelity (especially tables) and retrieval relevance. Measured by precision/recall on extraction and by correctness of answers with correct provenance.

- **Robustness.** Graceful degradation on unseen layouts and document types. Strategy escalation and confidence gates prevent silent failure; config allows tuning without code change.

- **Cost-awareness.** Explicit cost tiers (fast text < layout < vision). Budget guards and per-document cost tracking; strategy selection minimizes cost while meeting quality thresholds.

- **Auditability.** Every fact has bbox + page; every answer has ProvenanceChain; extraction ledger records strategy and confidence. Claims can be verified against source.

- **Configurability.** Thresholds, strategy routing, chunking rules, and feature flags in config (e.g. extraction_rules.yaml). New document types or policy changes do not require code changes (constitution: config-over-code).

---

## 9. Risks, Tradeoffs, and Open Questions

- **VLM cost and latency.** Vision-augmented extraction is expensive. Tradeoff: quality vs. cost per document. Mitigation: strict escalation rules, budget caps, and use of cheaper models where acceptable. Open: how to set thresholds across diverse client corpora.

- **Document variability.** Layouts, languages, and domains vary widely. One corpus may not represent all clients. Risk: overfitting to current corpus; under-generalization. Mitigation: document-aware chunking and config-driven rules so new classes can be onboarded via config and minimal tuning. Open: minimal set of document classes and rules that generalize.

- **Schema evolution.** ExtractedDocument, LDU, and PageIndex schemas may need to evolve as new content types or clients appear. Risk: breaking existing pipelines and stored artifacts. Open: versioning and migration strategy for Pydantic models and persisted data.

- **PageIndex quality.** Section detection and summarization depend on extraction quality and LLM summaries. Weak extraction or generic summaries reduce PageIndex usefulness. Tradeoff: cost of better section/summary models vs. retrieval precision.

- **Provenance granularity.** Bbox + page is mandatory; sub-page or cell-level provenance may be required for tables. Open: standard for table-cell provenance and impact on storage and query API.

---

## 9. Deliverables (Refinery Guide §8)

The Document Intelligence Refinery Guide §8 defines **Interim** and **Final** submission deliverables. This section maps them to this spec and the codebase (excluding report PDFs, generated artifacts, and video submission).

### 9.1 Interim — Core Models & Agents (Phases 1–2)

| Guide deliverable | Location / spec | Status |
|-------------------|-----------------|--------|
| **Core Models** — DocumentProfile, ExtractedDocument, LDU, PageIndex, ProvenanceChain | `src/models/` — spec [07](../specs/07-models-schemas-spec.md) §3–5, §6, §7 | Implemented: DocumentProfile, ExtractedDocument, LDU, PageIndex/PageIndexSection, ProvenanceChain/ProvenanceItem. |
| **Triage Agent** — origin_type, layout_complexity, domain_hint | `src/agents/triage.py` — spec [02](../specs/02-triage-agent-and-document-profile.md) | Implemented. |
| **Strategies** — FastTextExtractor, LayoutExtractor, VisionExtractor, shared interface | `src/strategies/` — spec [03](../specs/03-multi-strategy-extraction-engine.md) | FastTextExtractor + base interface; Layout/Vision stubs or adapters per tasks. |
| **ExtractionRouter** — confidence-gated escalation | `src/agents/extractor.py` — plan [phase-2](../plans/phase-2-extraction.plan.md) §4 | Implemented. |
| **Configuration** — extraction_rules.yaml, .refinery/profiles/, extraction_ledger.jsonl | `rubric/extraction_rules.yaml`, `.refinery/` | Implemented. |
| **Project setup** — pyproject.toml, README with setup and run instructions | Root | Implemented. |
| **Tests** — Triage and extraction confidence scoring | `tests/` | Implemented. |

### 9.2 Final — Agents (Phases 3–4) & Data Layer

| Guide deliverable | Location / spec | Status |
|-------------------|-----------------|--------|
| **Semantic Chunking Engine** — all 5 chunking rules, ChunkValidator | `src/agents/chunker.py` (entry) + `src/chunking/` — spec [04](../specs/04-semantic-chunking-and-ldu-spec.md) §6 | ChunkValidator + emit_ldus in `src/chunking/`; chunker.py re-exports. ChunkingEngine (ExtractedDocument → LDUs) per tasks. |
| **PageIndex tree builder** — LLM section summaries | `src/agents/indexer.py` — spec [05](../specs/05-pageindex-builder-spec.md) | Per phase-3 tasks (P3-T005+). |
| **Query agent** — LangGraph, pageindex_navigate, semantic_search, structured_query | `src/agents/query_agent.py` — spec [06](../specs/06-query-agent-and-provenance-spec.md) | Per phase-4 tasks. |
| **FactTable** — SQLite backend, numerical documents | Data layer — spec 06 §5, spec 07 §8 | Per phase-4 tasks. |
| **Vector store** — ChromaDB or FAISS, ingest LDUs | Data layer | Per phase-3/4 tasks. |
| **Audit Mode** — claim verification, citation or "unverifiable" | `src/agents/audit.py` — spec 06 §7–8 | Implemented. |

### 9.3 Invariants (from Guide)

- **Escalation guard:** Strategy A must not pass low-confidence output; router escalates and ledger records chain.
- **Provenance:** Every answer carries ProvenanceChain (document, page, bbox, content_hash); audit mode returns verified or explicit unverifiable.
- **Config-over-code:** Thresholds and rules in `extraction_rules.yaml` (and equivalent); no hardcoded magic numbers.

---

**Version:** 1.0  
**Spec status:** System-level; implementation plans will reference this spec and the constitution.
