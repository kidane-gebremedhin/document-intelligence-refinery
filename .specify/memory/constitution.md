# Document Intelligence Refinery — Constitution

This constitution defines non-negotiable principles for specs, plans, and implementation. Every feature and design decision must align with it.

---

## Core Principles

**I. Multi-strategy, cost-aware extraction**

- Extraction follows a defined escalation path: fast text → layout/structure → VLM only when needed.
- Cheaper strategies are tried first; cost and latency are explicit design criteria.
- Specs and plans must state which strategy applies and when escalation is allowed. No “VLM for everything.”

**II. Spatial provenance is non-negotiable**

- Every extracted fact carries a bounding box (bbox) and page reference.
- No fact exists without provenance; “page + bbox” is the default, not optional.
- Specs that introduce new extraction outputs must require provenance fields. Tables, key–value pairs, and entities all get bbox + page.

**III. Document-aware chunking**

- Chunking respects document structure: sections, tables, lists, figures—not arbitrary token windows.
- Token-based slicing that cuts through tables or mid-paragraph is prohibited.
- Chunk boundaries must be justified by structure (e.g. “by section”, “by table”, “by block”), not by token count alone.

**IV. PageIndex-first retrieval**

- Retrieval uses a PageIndex (or equivalent page/structure index) before falling back to naive vector search.
- “Which page(s)?” is answered first; vector search refines within that scope when needed.
- Specs for RAG, QA, or search must describe the PageIndex contract and when vector search is used.

**V. Testable, typed data contracts**

- Every data contract (inputs, outputs, intermediate payloads) is expressed as a Pydantic model.
- Types are strict enough to be testable: validation, serialization, and schema generation are required.
- New APIs or pipelines must define Pydantic models first; ad-hoc dicts or untyped structures are not allowed.

**VI. Config-over-code**

- Thresholds, strategy routing, and feature flags live in configuration, not hardcoded logic.
- Changes to “when do we use VLM?” or “what’s the chunk size?” are config changes, not code changes.
- Specs must identify which knobs are configurable and where they live (e.g. config file, env).

---

## Enforcement

- **Specs**: Every spec must reference the relevant constitution principles and show compliance (e.g. “provenance: bbox + page on all outputs”, “chunking: document-aware, no token-sliced tables”).
- **Plans**: Implementation plans must list concrete deliverables that satisfy these principles (e.g. “Pydantic models for X”, “PageIndex interface before vector search”).
- **Reviews**: PRs and design reviews check alignment with this constitution; violations require justification or amendment.

---

## Governance

This constitution overrides conflicting local practices. Amendments require a documented proposal, impact on existing specs/plans, and an explicit ratification note below.

**Version**: 1.0 | **Ratified**: 2025-03-03
