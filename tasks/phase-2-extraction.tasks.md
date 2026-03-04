# Phase 2: Multi-Strategy Extraction Engine — Tasks

**Source plan:** [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md)  
**Spec:** [03 – Multi-Strategy Extraction Engine](../specs/03-multi-strategy-extraction-engine.md)  
**Models:** [07 – Models & Schemas](../specs/07-models-schemas-spec.md) (§4 ExtractedDocument, §9.1 ExtractionLedgerEntry).

---

## P2-T001 — ExtractedDocument and related Pydantic models

**Description:** Define Pydantic models for the extraction output so all strategies emit a unified schema. Implement: `TextBlock`, `Table`, `TableHeader`, `TableRow`, `TableCell`, `Figure`, `ReadingOrderEntry` (or equivalent), and `ExtractedDocument` per [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4 and the logical schema in [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §3. ExtractedDocument must include `document_id`, `strategy_used`, `strategy_confidence`, `pages`, `text_blocks`, `tables`, `figures`, and reading order (e.g. `reading_order` list or ordering on blocks). Every element in text_blocks, tables, figures must have non-null page and bbox (BoundingBox). Add validators or invariants so that page numbers are in [1, pages] and reading_order refs match existing IDs.

**Files:**
- `src/models/` (or project equivalent) — ExtractedDocument, TextBlock, Table, Figure, ReadingOrderEntry, BoundingBox
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4, [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §3

**Acceptance criteria:**
- ExtractedDocument can be instantiated with required fields; serialization to JSON round-trips.
- A validator or test rejects ExtractedDocument when any text_block/table/figure has missing page or bbox.
- A test that builds an ExtractedDocument with strategy_used and strategy_confidence set passes validation.

---

## P2-T002 — BaseExtractor interface and extraction result type

**Description:** Define the **BaseExtractor** interface (protocol, abstract base class, or callable type) so the router can delegate to any strategy uniformly. Signature: `extract(doc_path, profile) -> result`. Define a **result type** that represents either (1) success: `ExtractedDocument` + confidence score in [0, 1], or (2) escalation/failure: no document, with a reason (e.g. `confidence_below_threshold`, `error`). The router will use this to decide whether to emit output or try the next strategy. Document the contract: success only when output conforms to ExtractedDocument and confidence ≥ threshold (threshold applied by router); extractors return raw result, router compares to threshold.

**Files:**
- Extraction strategy module or `src/strategies/` (e.g. `base.py` or `interfaces.py`)
- [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md) §2, [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md)

**Acceptance criteria:**
- BaseExtractor (or equivalent) is defined and documentable (e.g. protocol with `extract(doc_path, profile)`).
- Result type can represent success (document + confidence) and failure/escalation (reason, no document).
- A stub extractor that returns success and one that returns escalation can be used interchangeably from a single “router” test (no real PDF).

---

## P2-T003 — FastTextExtractor: extract and map to ExtractedDocument

**Description:** Implement **FastTextExtractor** using pdfplumber or pymupdf. Given `doc_path` and `profile`, open the PDF, extract text and character/word/line objects with bbox and page, and map the result to **ExtractedDocument**: text_blocks with id, content (or text), page, bbox, optional block_type; tables and figures may be empty lists or heuristic placeholders; reading_order derived from page order and vertical position. Set `strategy_used="fast_text"` and a placeholder `strategy_confidence` (e.g. 0.5) for now; full confidence logic is P2-T004. Ensure every text_block has non-null page and bbox per [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §3 and [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4.

**Files:**
- `src/strategies/` or `src/agents/` — FastTextExtractor
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §4, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4

**Acceptance criteria:**
- Given a valid PDF path and a DocumentProfile, FastTextExtractor.extract() returns a result containing an ExtractedDocument (success case) with at least one text_block when the PDF has text.
- Every text_block in the output has page and bbox set; document_id matches profile.document_id; strategy_used is "fast_text".
- A test or run on a known PDF produces an ExtractedDocument that passes ExtractedDocument validation (e.g. model validators).

---

## P2-T004 — FastTextExtractor: confidence scoring and escalate signal

**Description:** Implement extraction **confidence scoring** for FastTextExtractor per [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §4.2. Compute a score in [0, 1] using at least: character count per page (low → lower confidence), character density (chars per page area), image area ratio (high with low text → lower confidence), font metadata presence. Load thresholds from config (e.g. min character count per page, max image area ratio). If confidence is below the configured threshold, **do not** return an ExtractedDocument; return an escalation/failure result (e.g. “confidence_below_threshold”) so the router will try Strategy B. No hardcoded thresholds; all from extraction_rules.yaml or equivalent.

**Files:**
- FastTextExtractor (same as P2-T003), config file
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §4.2–4.3, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md)

**Acceptance criteria:**
- Unit test: given a PDF (or fixture) with high character count and low image area, confidence score is above the configured threshold.
- Unit test: given a PDF (or fixture) with very low character count or high image area, confidence score is below threshold (or changing config flips outcome).
- Unit test or assertion: the score incorporates character count, character density, image area ratio, and font metadata (e.g. mock where one signal is bad and score drops).
- When confidence is below threshold, the extractor returns an escalation result (no ExtractedDocument).

---

## P2-T005 — LayoutExtractor: adapter to ExtractedDocument

**Description:** Implement **LayoutExtractor** that uses Docling or MinerU to extract structure, then **adapt** the tool’s output to the internal **ExtractedDocument** schema per [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §5. Input: doc_path, profile. Output: ExtractedDocument with text_blocks (id, content, page, bbox, optional block_type), tables (id, page, bbox, headers, rows, num_rows, num_cols, optional caption), figures (id, page, bbox, caption, alt_text), and reading_order (ref_type, ref_id, order). Ensure every element has non-null page and bbox; reading_order consistent with IDs. Set strategy_used="layout" and strategy_confidence (optional: from layout model or heuristic). If the layout tool is not yet integrated, a **mock adapter** that returns a valid ExtractedDocument from a fixture or minimal PDF is acceptable so the router and ledger can be tested.

**Files:**
- `src/strategies/` — LayoutExtractor, Docling/MinerU adapter (or mock)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §5, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4

**Acceptance criteria:**
- LayoutExtractor implements the BaseExtractor interface (extract(doc_path, profile)).
- For at least one input (real Docling/MinerU run or mock), the output is a valid ExtractedDocument with text_blocks, tables, figures (or empty), and reading_order; all elements have page and bbox.
- strategy_used is "layout"; strategy_confidence is set (e.g. 0.0–1.0 or constant for mock).

---

## P2-T006 — VisionExtractor: stub and budget guard hook interface

**Description:** Implement **VisionExtractor** as a **stub** that satisfies the BaseExtractor interface: accept `doc_path` and `profile`, return a clear “not implemented” or “stub” result (no ExtractedDocument, or a minimal placeholder with a flag). The router must be able to call it and record strategy_used and escalation_path when C is selected. Define the **budget guard hook interface** (e.g. `check_budget(document_id, estimated_tokens) -> bool`; `record_usage(document_id, prompt_tokens, completion_tokens)`) so that when Strategy C is implemented later, the router can call these before/after VisionExtractor without changing the router’s control flow. Document input/output design for a full VisionExtractor (page images, prompt template, domain_hint; output normalized to ExtractedDocument) per plan §3.3.

**Files:**
- `src/strategies/` — VisionExtractor (stub), budget guard module or interface
- [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md) §3.3, §4.4, [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §6

**Acceptance criteria:**
- VisionExtractor.extract(doc_path, profile) returns an escalation/failure result (e.g. “not_implemented” or “stub”) and does not return a valid ExtractedDocument (or returns a placeholder that is explicitly marked stub).
- Budget guard interface is defined and callable (e.g. check_budget returns bool; record_usage accepts token counts); router or test can call it without error.
- Document or docstring describes the intended full VisionExtractor input (page images, prompts, domain_hint) and output (ExtractedDocument) and budget cap behavior.

---

## P2-T007 — ExtractionLedgerEntry model and JSONL append

**Description:** Define the **ExtractionLedgerEntry** Pydantic model per [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §9.1 and [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §9. Fields: document_id, strategy_used, origin_type, layout_complexity, start_time, end_time, processing_time_ms (or processing_time_seconds), confidence_score, cost_estimate_usd (or cost_estimate), token_usage_prompt, token_usage_completion (optional), escalation_chain, notes. Invariants: end_time >= start_time; strategy_used equals last element of escalation_chain when a strategy succeeded. Implement **append** of one serialized entry per run to `.refinery/extraction_ledger.jsonl` (or configurable path). Datetimes as ISO 8601. Append-only; do not overwrite or delete existing lines.

**Files:**
- `src/models/` — ExtractionLedgerEntry
- Extraction ledger writer (e.g. in router or `src/refinery/ledger.py`)
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §9.1, [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §9

**Acceptance criteria:**
- ExtractionLedgerEntry validates with required fields; serialization to JSON round-trips; end_time >= start_time enforced.
- Writing an entry appends one JSON line to the ledger file; re-running adds a new line (no overwrite).
- A test or script writes two entries and reads the file; both lines are valid JSON and contain document_id, strategy_used, confidence_score, escalation_chain (or equivalent).

---

## P2-T008 — ExtractionRouter: initial strategy selection and single extractor call

**Description:** Implement **ExtractionRouter** that (1) accepts doc_path and profile (or document_id and loads profile from `.refinery/profiles/{document_id}.json`), (2) selects the **initial strategy** using the decision tree in [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §7.1: if scanned_image or needs_vision_model → Strategy C; else if native_digital and single_column → Strategy A; else → Strategy B. (3) Calls the chosen extractor’s `extract(doc_path, profile)` once. Do not yet implement escalation (single call only). Return the extractor result and which strategy was tried. Load confidence thresholds from config so they can be used in the next task.

**Files:**
- `src/agents/extractor.py` or `src/strategies/router.py` — ExtractionRouter
- Config (confidence thresholds)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §7.1

**Acceptance criteria:**
- Given a profile with origin_type=scanned_image, the router selects Strategy C (and calls VisionExtractor).
- Given a profile with native_digital and layout_complexity=single_column, the router selects Strategy A (and calls FastTextExtractor).
- Given a profile with layout_complexity=multi_column, the router selects Strategy B (and calls LayoutExtractor).
- A test or run executes the router and verifies the correct extractor was invoked (e.g. by result or mock).

---

## P2-T009 — ExtractionRouter: escalation loop (no low-confidence output)

**Description:** Extend ExtractionRouter so that after calling an extractor, it **evaluates the result**: if the extractor returned an ExtractedDocument and confidence ≥ configured threshold, emit that and stop. If the extractor returned escalation (confidence below threshold or error), **do not** emit that extractor’s output; try the **next** strategy in the escalation path (A→B→C). Repeat until a strategy returns acceptable output or all are exhausted. When all fail, return a failure result (no ExtractedDocument) with explicit reason. Ensure Strategy A never passes low-confidence output downstream (constitution: escalation guard mandatory).

**Files:**
- ExtractionRouter (same as P2-T008), config (fast_text_confidence_threshold, layout_confidence_threshold)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §7.2, [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md) §4.3

**Acceptance criteria:**
- Unit test: profile permits Strategy A (native_digital, single_column) but fixture/document produces low Strategy A confidence → router does **not** emit A’s output; router tries B (or C) and emits B’s (or C’s) result or failure.
- Unit test or run: after such a run, the router’s internal escalation path includes "fast_text" and the final strategy (e.g. "layout"); no ExtractedDocument with strategy_used="fast_text" is returned when A escalated.

---

## P2-T010 — ExtractionRouter: write ledger entry and escalation_chain

**Description:** After each extraction run (success or failure), the router **writes one ExtractionLedgerEntry** and appends it to `.refinery/extraction_ledger.jsonl`. Entry must include: document_id, strategy_used (final strategy that produced output, or e.g. "escalation_failed"), origin_type, layout_complexity, start_time, end_time, processing_time_ms (or seconds), confidence_score, cost_estimate (0 for A/B if no API), escalation_chain (ordered list of strategies attempted), notes (e.g. "confidence_below_threshold" when escalation occurred). When a strategy succeeds, strategy_used must equal the last element of escalation_chain; when all fail, strategy_used may be "escalation_failed" and escalation_chain lists all attempted strategies.

**Files:**
- ExtractionRouter, ledger writer (from P2-T007)
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §9.1, [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §9

**Acceptance criteria:**
- After a successful extraction run, the ledger file has one new line; the line parses as JSON and contains document_id, strategy_used, confidence_score, processing_time (or equivalent), escalation_chain.
- After a run that escalated (e.g. A→B), escalation_chain in the entry is e.g. ["fast_text", "layout"] and strategy_used is "layout"; notes or equivalent indicates escalation.
- After a run where all strategies fail, strategy_used is "escalation_failed" (or similar) and escalation_chain lists all attempted strategies.

---

## P2-T011 — Budget guard: check cap and record usage (Strategy C hooks)

**Description:** Implement the **budget guard** module or callbacks: (1) **check_budget(document_id, estimated_tokens_or_cost)** — returns whether proceeding would exceed the configured per-document cap; (2) **record_usage(document_id, prompt_tokens, completion_tokens, cost)** — records usage for the run. The ExtractionRouter must call check_budget **before** invoking Strategy C (and optionally before each page batch if C is incremental). If the cap would be exceeded, the router must not call Strategy C (or must stop); log and fail or emit “budget exceeded.” After Strategy C runs, call record_usage. Strategy A and B may pass cost 0. Config: per-document cap (tokens or USD), optional cost per 1K tokens.

**Files:**
- Budget guard module (e.g. `src/strategies/budget_guard.py` or equivalent)
- ExtractionRouter (call hooks when using Strategy C)
- Config (max cost or tokens per document)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §8, [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md) §4.4

**Acceptance criteria:**
- check_budget(document_id, 0) returns True (no usage yet); after record_usage with a value below cap, check_budget with estimated remaining returns True or False per config.
- When cap is set and estimated usage would exceed it, the router does not invoke Strategy C (or stops); a test or run demonstrates this (e.g. stub C with high estimated cost).
- Ledger or log records budget-related behavior (e.g. notes when cap exceeded).

---

## P2-T012 — Unit tests: confidence scoring and ExtractedDocument invariants

**Description:** Add or consolidate **unit tests** for (1) **Strategy A confidence**: high character count + low image area → score above threshold; low character count or high image area → score below threshold; score incorporates character count, density, image area, font metadata (one test or assertion per signal). (2) **ExtractedDocument invariants**: for at least one successful extraction (A or B), the output has non-empty document_id; every text_block, table, figure has non-null page and bbox; reading_order refs match IDs; strategy_used and strategy_confidence set. Use validators or explicit assertions. (3) **Ledger shape**: after one full router run, the ledger file exists and at least one line has document_id, strategy_used, confidence_score, processing_time, escalation_chain.

**Files:**
- Test module (e.g. `tests/test_extraction.py`, `tests/strategies/`)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §3–4, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §4, §9

**Acceptance criteria:**
- At least two tests for Strategy A confidence (above threshold case, below threshold case or config-driven).
- At least one test that validates ExtractedDocument invariants (page, bbox, reading_order consistency) on a real or fixture extraction output.
- At least one test that reads the ledger file after a run and asserts presence of document_id, strategy_used, confidence_score, escalation_chain (or equivalent fields).

---

## P2-T013 — Unit test: router escalation (low-confidence A → B)

**Description:** Add a **single end-to-end test** for router escalation: (1) Use a DocumentProfile that permits Strategy A (origin_type=native_digital, layout_complexity=single_column). (2) Use a document or mock that causes FastTextExtractor to return **low confidence** (e.g. low character count PDF, or a mock extractor that returns confidence below threshold). (3) Run the ExtractionRouter. (4) Assert: the router does **not** return an ExtractedDocument with strategy_used="fast_text"; it returns either an ExtractedDocument from Strategy B (or C) or a failure result. (5) Assert: the ledger entry for this run has escalation_chain containing "fast_text" and the final strategy (e.g. "layout"), and notes or equivalent indicate escalation (e.g. "confidence_below_threshold").

**Files:**
- Test module (e.g. `tests/test_router_escalation.py` or inside extraction tests)
- [specs/03-multi-strategy-extraction-engine.md](../specs/03-multi-strategy-extraction-engine.md) §7.2, [plans/phase-2-extraction.plan.md](../plans/phase-2-extraction.plan.md) §6.2

**Acceptance criteria:**
- Test runs and passes: low-confidence Strategy A triggers escalation; emitted result is not from A; ledger has correct escalation_chain and strategy_used.
- Test is repeatable (e.g. pytest); uses fixture or mock so it does not depend on a specific external PDF unless required.

---

## Phase 2 completion

When P2-T001 through P2-T013 are complete and their acceptance criteria met, Phase 2 acceptance checks in the plan (§6) are satisfied: ExtractedDocument model and invariants, BaseExtractor and three strategies (A with confidence and escalate, B with adapter, C stub with budget hooks), ExtractionRouter with decision tree and escalation guard, ledger write with escalation_chain, budget guard hooks, unit tests for confidence and invariants, and at least one test for router escalation behavior.
