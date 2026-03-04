# Phase 1: Triage Agent & Document Profiling — Tasks

**Source plan:** [plans/phase-1-triage.plan.md](../plans/phase-1-triage.plan.md)  
**Model reference:** [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) (§3 DocumentProfile — fields, enums, invariants).

---

## P1-T001 — Config skeleton and profile output path

**Description:** Add a configuration skeleton for triage (e.g. `extraction_rules.yaml` or `config/triage.yaml`) with placeholder sections for: origin_type thresholds (min character count per page, max image area ratio, fraction of pages for “mixed”), layout_complexity thresholds (table area ratio, table count per page, figure area ratio), domain_hint (keyword sets per domain, confidence cutoff). Define the profile output path convention: `.refinery/profiles/{document_id}.json`. Implement or document `document_id` derivation (e.g. hash of file path or first N bytes) so the same document yields a stable ID. Ensure the profiles directory is created when triage runs (or document the expectation that it exists).

**Files:**
- Config file (e.g. `extraction_rules.yaml`, `config/triage.yaml`, or project-chosen path)
- Optional: small module or function that loads config and resolves profile path / document_id
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) (invariant: `document_id` must match filenames in `.refinery/profiles/{document_id}.json`)

**Acceptance criteria:**
- Config file exists with the above sections (values may be placeholders or Phase 0–derived defaults).
- Profile path is documented or implemented as `.refinery/profiles/{document_id}.json` (or equivalent per project).
- For the same PDF path, `document_id` is stable across runs (e.g. deterministic hash).
- A test or script run creates `.refinery/profiles/` when writing a profile (or doc states that caller must ensure directory exists).

---

## P1-T002 — DocumentProfile Pydantic model

**Description:** Define the `DocumentProfile` Pydantic model per [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3. Include all fields: `document_id`, `origin_type`, `layout_complexity`, `language`, `language_confidence`, `domain_hint`, `estimated_extraction_cost`, `triage_confidence_score`, `created_at`, optional `metadata`; add `page_count` and optional `notes` per plan/spec 02. Use literal types or enums for `origin_type`, `layout_complexity`, `domain_hint`, `estimated_extraction_cost`. Add a validator or post-validator that enforces: (1) `origin_type == "scanned_image"` → `estimated_extraction_cost == "needs_vision_model"`; (2) `layout_complexity` in `table_heavy` | `multi_column` | `figure_heavy` | `mixed` → `estimated_extraction_cost` in `needs_layout_model` | `needs_vision_model`; (3) only when `origin_type == "native_digital"` and `layout_complexity == "single_column"` may `estimated_extraction_cost == "fast_text_sufficient"`. Ensure `triage_confidence_score` and `language_confidence` are in [0, 1].

**Files:**
- `src/models/` (or project equivalent) — DocumentProfile model
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Model instantiation with valid fields produces a valid profile; serialization to JSON round-trips.
- Invalid enum values raise a validation error.
- A unit test that passes a valid dict for native_digital + single_column yields `estimated_extraction_cost == "fast_text_sufficient"`.
- A unit test that passes `origin_type="scanned_image"` and `estimated_extraction_cost="needs_layout_model"` raises (validator rejects).
- A unit test that passes `layout_complexity="table_heavy"` and `estimated_extraction_cost="fast_text_sufficient"` raises (validator rejects).

---

## P1-T003 — origin_type detection

**Description:** Implement origin_type detection using character density (or character count per page), image area ratio, font metadata presence, and page-level aggregation. Load thresholds from the config added in P1-T001 (min character count per page for “digital”, max image area ratio, fraction of pages for “mixed”). Return one of: `native_digital`, `scanned_image`, `mixed`, `form_fillable`. Detect form_fillable via PDF AcroForm if available. Resolve conflicting signals with a defined rule order (e.g. all pages zero chars → `scanned_image`). No hardcoded magic numbers; all thresholds from config.

**Files:**
- Triage/origin detection module (e.g. `src/agents/triage.py` or `src/triage/origin.py`)
- Config file (from P1-T001)
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §5.1, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Unit test: given a PDF (or mock) with high character count and low image area, origin_type is `native_digital`.
- Unit test: given a PDF (or mock) with zero or negligible character count on all pages, origin_type is `scanned_image`.
- Unit test: given a PDF (or mock) where only a fraction of pages have sufficient character count, origin_type is `mixed` (or document behavior if different).
- Changing the min character count in config and re-running changes the outcome for a borderline fixture (or test with two configs).

---

## P1-T004 — layout_complexity detection

**Description:** Implement layout_complexity detection using column-count heuristic (e.g. from character bbox clustering or line positions), table presence (table area ratio and/or table region count per page), and figure/image area ratio. Load thresholds from config (table_heavy, figure_heavy). Apply dominance rule: if both table and figure ratios high or neither dominates → `mixed`. Return one of: `single_column`, `multi_column`, `table_heavy`, `figure_heavy`, `mixed`. No hardcoded thresholds.

**Files:**
- Triage/layout detection module (e.g. same as P1-T003 or separate)
- Config file (from P1-T001)
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §5.2, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Unit test: given a PDF (or mock) with single text column and no significant table/figure area, layout_complexity is `single_column`.
- Unit test: given a PDF (or mock) with two or more columns (or heuristic indicating multi-column), layout_complexity is `multi_column`.
- Unit test: given a PDF (or mock) with table area ratio above configured threshold (or table count above threshold), layout_complexity is `table_heavy` (or `mixed` if figure also high).
- Changing table_heavy threshold in config and re-running changes the outcome for a borderline fixture where applicable.

---

## P1-T005 — domain_hint classifier (keyword-based, pluggable)

**Description:** Implement a keyword-based domain_hint classifier: per-domain keyword sets (financial, legal, technical, medical), sample text from the document (e.g. first N pages via pdfplumber or equivalent), score by presence/frequency, assign domain with highest score if above confidence threshold else `general`. Load keyword sets and confidence cutoff from config. Expose the classifier as a pluggable strategy (e.g. protocol/interface or dependency injection) so a VLM or other implementation can be swapped without changing DocumentProfile schema. Return one of: `financial`, `legal`, `technical`, `medical`, `general`.

**Files:**
- Triage/domain classifier module
- Config file (keyword sets, confidence cutoff)
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §5.4, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Unit test: given text containing financial keywords (e.g. “revenue”, “balance sheet”), domain_hint is `financial` (with config that includes those keywords).
- Unit test: given text containing legal keywords, domain_hint is `legal`.
- Unit test: given text with no domain keywords (or below threshold), domain_hint is `general`.
- The classifier is replaceable: e.g. a test or example that plugs a stub returning a fixed domain and receives that value in the profile (no schema change).

---

## P1-T006 — estimated_extraction_cost derivation and invariants

**Description:** Implement the mapping from origin_type and layout_complexity to estimated_extraction_cost: (1) `origin_type == scanned_image` → `needs_vision_model`; (2) `origin_type == mixed` → at least `needs_layout_model` (optionally `needs_vision_model` if text-layer confidence low); (3) `layout_complexity` in `table_heavy` | `multi_column` | `figure_heavy` | `mixed` → at least `needs_layout_model`; (4) only when `origin_type == native_digital` and `layout_complexity == single_column` → `fast_text_sufficient`. Ensure this logic is used when building DocumentProfile so invariants in [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3 always hold.

**Files:**
- Triage module that computes or sets estimated_extraction_cost
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §4.5, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Unit test: for origin_type=scanned_image, estimated_extraction_cost is always needs_vision_model.
- Unit test: for layout_complexity in (table_heavy, multi_column), estimated_extraction_cost is needs_layout_model or needs_vision_model, never fast_text_sufficient.
- Unit test: for origin_type=native_digital and layout_complexity=single_column, estimated_extraction_cost is fast_text_sufficient (subject to any other guards, e.g. form_fillable).
- DocumentProfile built by triage always passes the model’s invariant validators when this logic is used.

---

## P1-T007 — triage_confidence_score and optional notes

**Description:** Implement triage_confidence_score in [0, 1] reflecting classification ambiguity. Lower score when: signals conflict (e.g. font suggests digital but character count zero), values are near threshold boundaries, or domain_hint is general due to weak keyword match. Optionally set `notes` when conflicting or ambiguous (e.g. “conflicting signals: defaulted to mixed”). Formula may combine per-dimension confidences (min, product, or weighted average); implementation-defined but must be stored in the profile.

**Files:**
- Triage module (confidence and notes)
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §5.5, [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Unit test: when origin_type and layout_complexity are “clear” (e.g. native_digital + single_column with strong signals), triage_confidence_score is relatively high (e.g. ≥ 0.6).
- Unit test: when signals conflict (e.g. mock with zero chars but font metadata present) or borderline thresholds, triage_confidence_score is lower than in the clear case, or `notes` is non-empty.
- Every emitted profile has triage_confidence_score in [0, 1].

---

## P1-T008 — Triage pipeline: PDF in → DocumentProfile out

**Description:** Wire the full triage pipeline: accept PDF path (and optional basic metadata), compute page_count, origin_type, layout_complexity, domain_hint, derive estimated_extraction_cost, compute triage_confidence_score and optional notes, set language/language_confidence (or `unknown`/0.0 if deferred). Build and return a DocumentProfile instance; validate with the model’s validators. Single entry point (e.g. `triage(pdf_path) -> DocumentProfile` or `TriageAgent.run(pdf_path)`). Handle only “success” path here; errors in P1-T011.

**Files:**
- Triage agent entry point (e.g. `src/agents/triage.py`)
- All detection and cost-derivation modules from P1-T003–P1-T007
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3

**Acceptance criteria:**
- Given a valid PDF path, the entry point returns a DocumentProfile with all required fields set (document_id, origin_type, layout_complexity, language, language_confidence, domain_hint, estimated_extraction_cost, triage_confidence_score, page_count, created_at).
- All DocumentProfile invariants hold (validators pass).
- A test or manual run on one PDF produces a valid profile (no missing fields, no invalid enums).

---

## P1-T009 — Persist DocumentProfile to JSON

**Description:** After building the DocumentProfile, write it to `.refinery/profiles/{document_id}.json`. Use the same document_id as in the profile (from P1-T001). Ensure the directory exists (create if missing). Serialize the profile to JSON (e.g. model_dump() + json.dump with datetime/ISO handling). Re-running triage on the same document overwrites the file. Document that the router (Stage 2) will load from this path by document_id.

**Files:**
- Triage module or a small persistence helper
- Config/path from P1-T001
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3 (document_id matches filename)

**Acceptance criteria:**
- After triage(pdf_path), a file exists at `.refinery/profiles/{document_id}.json` and document_id in the file matches the filename stem.
- Reading the JSON and deserializing yields a DocumentProfile that validates (round-trip).
- Running triage again on the same PDF overwrites the same file (same document_id).
- Example: run triage on a sample PDF; list `.refinery/profiles/` and open the JSON; all fields present and valid.

---

## P1-T010 — Triage run logging

**Description:** Log every triage run in a machine-readable format (e.g. JSON lines). Each log entry must include: document_id, timestamp, outcome (success | error), and either the emitted DocumentProfile (as JSON or key fields) or the error reason. Triage_confidence_score and notes must be included when present. Log to a file (e.g. `.refinery/triage_log.jsonl`) or to a configurable stream.

**Files:**
- Triage module or logging helper
- [plans/phase-1-triage.plan.md](../plans/phase-1-triage.plan.md) §5.4

**Acceptance criteria:**
- After one successful triage run, at least one log entry exists with document_id, timestamp, outcome=success, and profile (or required profile fields).
- After one failed run (e.g. unreadable file), a log entry exists with outcome=error and error reason.
- Log format is JSON lines (one JSON object per line) or otherwise machine-parseable.

---

## P1-T011 — Error handling: unreadable file, empty PDF, corrupt input

**Description:** When the PDF cannot be opened, is empty (zero pages), or is corrupt, do not write a normal DocumentProfile. Emit an explicit error (exception or structured error result) and optionally log (see P1-T010). Do not silently return a profile with default or null values for required fields. If the schema supports a sentinel/error state (e.g. optional error field or separate result type), use it; otherwise fail fast and let the caller handle missing profile.

**Files:**
- Triage entry point and any file-opening logic
- [specs/02-triage-agent-and-document-profile.md](../specs/02-triage-agent-and-document-profile.md) §6

**Acceptance criteria:**
- Unit test: unreadable path (or missing file) raises an error or returns an error result; no profile file is written at `.refinery/profiles/` for that document.
- Unit test: empty PDF (zero pages) raises an error or returns an error result; no valid profile is written.
- If a corrupt or malformed PDF is provided, triage does not write a valid profile; error is logged or raised.

---

## P1-T012 — Unit tests for origin_type, layout_complexity, domain_hint, and invariants

**Description:** Add or consolidate unit tests so that: (1) origin_type is tested for at least native_digital, scanned_image, and mixed (with fixtures or mocks); (2) layout_complexity is tested for at least single_column, multi_column, and table_heavy; (3) domain_hint is tested for at least financial, legal, technical, and general; (4) invariant tests: scanned_image → needs_vision_model; table_heavy/multi_column → cost at least needs_layout_model; native_digital + single_column → fast_text_sufficient. Use real PDFs from the corpus where possible, or minimal fixtures/mocks with clear expected outcomes.

**Files:**
- Test module (e.g. `tests/test_triage.py` or `tests/agents/test_triage.py`)
- Fixtures or sample PDFs (if any)
- [specs/07-models-schemas-spec.md](../specs/07-models-schemas-spec.md) §3, [plans/phase-1-triage.plan.md](../plans/phase-1-triage.plan.md) §5.1

**Acceptance criteria:**
- At least one test per origin_type value (or per detectable value) with expected outcome.
- At least one test per layout_complexity value (or per targeted value) with expected outcome.
- At least one test per domain_hint value (or subset) including general.
- Invariant tests as above; all pass. Test run is repeatable (e.g. pytest).

---

## P1-T013 — Sample run: profiles for at least three documents

**Description:** Run the Triage Agent on at least three documents spanning different classes (e.g. one native digital, one scanned, one table-heavy or multi-column). Verify: (1) for each document, a profile JSON exists at `.refinery/profiles/{document_id}.json`; (2) each JSON contains all required DocumentProfile fields and satisfies invariants; (3) triage_confidence_score and estimated_extraction_cost are consistent with origin_type and layout_complexity; (4) document class (A–D) aligns reasonably with profile (e.g. Class B → scanned_image, needs_vision_model; Class A → multi_column or table_heavy, needs_layout_model). Document the run (e.g. which files were used, one example profile snippet) and any mismatches.

**Files:**
- Sample PDFs (corpus or project-provided)
- `.refinery/profiles/*.json` (output)
- Optional: short doc or checklist (e.g. in README or `docs/phase1-sample-run.md`)

**Acceptance criteria:**
- At least three profile JSON files exist after the run.
- Each profile has document_id, origin_type, layout_complexity, domain_hint, estimated_extraction_cost, triage_confidence_score, page_count; invariants hold.
- Brief evidence of class alignment (e.g. “Doc X (scanned) → scanned_image, needs_vision_model”) is recorded.
- Example output: one full profile JSON (or key fields) included in task doc or README as example.

---

## Phase 1 completion

When P1-T001 through P1-T013 are complete and their acceptance criteria met, Phase 1 acceptance checks in the plan (§5) are satisfied: DocumentProfile model and persistence, config-driven thresholds, unit tests for all classification dimensions and invariants, error handling, logging, and a sample run producing at least three profiles with evidence of correct routing and invariants.
