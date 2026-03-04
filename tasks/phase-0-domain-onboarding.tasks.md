# Phase 0: Domain Onboarding — Tasks

**Source plan:** [plans/phase-0-domain-onboarding.plan.md](../plans/phase-0-domain-onboarding.plan.md)  
**Phase rule:** No code required; documentation and conceptual artifacts only.

---

## P0-T001 — Create DOMAIN_NOTES.md with section outline

**Description:** Create the deliverable file `DOMAIN_NOTES.md` with the full section outline from the plan. Populate only headings and short placeholders so later tasks know where to add content. Do not fill in experiment outcomes yet.

**Files:**
- `DOMAIN_NOTES.md` (create)

**Acceptance criteria:**
- File exists at repo root (or path specified by project convention).
- Outline includes: (1) Pipeline diagram, (2) Extraction strategy decision tree (draft), (3) Failure modes observed, (4) MinerU and Docling notes, (5) pdfplumber and metrics, (6) Chunking risks.
- Each section has a clear heading; placeholder text is acceptable (e.g. "To be filled by P0-T002").

---

## P0-T002 — MinerU: architecture summary and pipeline diagram

**Description:** Read MinerU architecture documentation end-to-end. Document: pipeline stages (e.g. PDF-Extract-Kit → Layout Detection → Formula/Table Recognition → Markdown export), whether each stage is classical CV/heuristics vs. neural layout vs. VLM. Classify as pipeline vs. VLM vs. hybrid. Add a pipeline diagram (Mermaid or hand-drawn) to DOMAIN_NOTES.md showing inputs, stages, outputs. Note where MinerU fits in the refinery (Strategy B).

**Files:**
- `DOMAIN_NOTES.md`
- External: MinerU docs (e.g. GitHub, project docs)

**Acceptance criteria:**
- DOMAIN_NOTES.md contains a short MinerU architecture summary (pipeline vs. VLM vs. hybrid).
- A pipeline diagram (Mermaid or hand-drawn) is present showing MinerU stages and data flow.
- Refinery role (Strategy B / layout-aware) is stated.

---

## P0-T003 — MinerU: intermediate artifacts and adapter implications

**Description:** Document MinerU’s intermediate artifacts (e.g. layout bboxes, table regions, cell grids, formula masks). Describe what would be needed to normalize MinerU output into the ExtractedDocument schema (text_blocks, tables, figures, reading_order). Add this to the MinerU section of DOMAIN_NOTES.md.

**Files:**
- `DOMAIN_NOTES.md`
- External: MinerU docs or code (inspection only)

**Acceptance criteria:**
- Intermediate artifacts are listed with brief descriptions.
- Adapter implications for ExtractedDocument (what maps, what is missing or needs transformation) are documented in DOMAIN_NOTES.md.

---

## P0-T004 — Docling: DoclingDocument schema and mapping to ExtractedDocument

**Description:** Study Docling’s Document Representation Model (DoclingDocument or equivalent). Document: top-level structure; how text blocks, tables, figures, and reading order are represented; presence of bbox and page per element; table representation (headers, rows, cells); figure + caption binding. Map DoclingDocument fields to the logical ExtractedDocument schema (text_blocks, tables, figures, reading_order). Note gaps (e.g. no reading_order, different bbox format). Add “wrap vs. adapt” notes to DOMAIN_NOTES.md.

**Files:**
- `DOMAIN_NOTES.md`
- External: Docling docs or API (e.g. GitHub, DS4SD/docling)

**Acceptance criteria:**
- DOMAIN_NOTES.md contains a description of DoclingDocument (or equivalent) schema.
- A mapping or gap list to ExtractedDocument (text_blocks, tables, figures, reading_order) is documented.
- Wrap vs. adapt implications are noted.

---

## P0-T005 — Docling: run on provided documents and quality notes

**Description:** Run Docling on the same provided documents used for pdfplumber (or a representative subset, at least one per class A–D if available). Inspect output structure and quality. Add to DOMAIN_NOTES.md: qualitative comparison of Docling output vs. MinerU (if MinerU was also run) or vs. expectations; any structural or quality issues observed.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: provided documents (e.g. corpus or data path from project)

**Acceptance criteria:**
- Docling has been run on provided documents (via CLI, API, or existing script; no new code required).
- DOMAIN_NOTES.md contains qualitative notes on Docling output structure and quality on those documents.
- Comparison to MinerU or to “naive” extraction is included if applicable.

---

## P0-T006 — pdfplumber: bbox coordinates and provenance serialization

**Description:** Using pdfplumber on provided or sample PDFs, document: how bbox is reported (per character, line, word, etc.); coordinate system (origin, units); how to serialize bbox for audit (e.g. per block or per LDU). Note limitations (e.g. no bbox for embedded images). Add this to the pdfplumber section of DOMAIN_NOTES.md.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: The Document Intelligence Refinery Guide (reference-docs), specs mentioning bbox/provenance

**Acceptance criteria:**
- DOMAIN_NOTES.md documents how pdfplumber bbox works and the coordinate system.
- Serialization approach for provenance/audit is described.
- Stated limitations (e.g. images) are recorded.

---

## P0-T007 — pdfplumber: character density, whitespace ratio, and metrics by class

**Description:** Install pdfplumber and run it on the provided documents (or a representative subset, at least one per class A–D if available). Compute or estimate: character count per page, character density (chars per unit area), whitespace ratio; optionally image area ratio and font metadata presence. Record typical ranges or values per document class. Add a table or summary to DOMAIN_NOTES.md with implications for triage and Strategy A confidence gates (e.g. “meaningful character stream”, “image area must not dominate”).

**Files:**
- `DOMAIN_NOTES.md`
- Reference: provided documents

**Acceptance criteria:**
- pdfplumber has been run on provided documents (no new code required; use CLI, notebook, or existing script).
- DOMAIN_NOTES.md documents at least character density and whitespace ratio with observations per document class.
- Implications for thresholds (e.g. character count per page, image area ratio) are stated.

---

## P0-T008 — Chunking risks: tables (flattening, header/cell split, token-boundary example)

**Description:** Using a sample document (e.g. financial report), extract text with pdfplumber only. Observe: are tables flattened into lines? Are headers separated from cells? Describe or simulate a 512-token chunk boundary through a table and what gets severed. Document in DOMAIN_NOTES.md why “a 512-token chunk that bisects a financial table produces hallucinations” with a concrete example. Tie to the need for structure-preserving LDUs and the five chunking rules.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: provided documents (e.g. Class A or D)

**Acceptance criteria:**
- DOMAIN_NOTES.md contains a “Chunking risks” subsection (or equivalent) covering table flattening and header/cell split.
- A concrete example (or clear description) of a token-boundary split through a table is given.
- Link to LDU/chunking rules is stated.

---

## P0-T009 — Chunking risks: multi-column and headings

**Description:** On a multi-column document, extract raw text (e.g. with pdfplumber) and compare extraction order to visual reading order. Document where order is wrong and how that would break section or list semantics when chunking. For headings: note how they appear in raw extraction (font, numbering) and whether section boundaries can be detected without layout. Document risks for parent_section and PageIndex. Add to DOMAIN_NOTES.md.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: provided documents (e.g. Class A or C)

**Acceptance criteria:**
- DOMAIN_NOTES.md documents multi-column reading order issues with observations.
- DOMAIN_NOTES.md documents heading/section boundary detection risks and impact on parent_section and PageIndex.
- Connection to need for layout-aware extraction (Strategy B) when structure matters is stated.

---

## P0-T010 — Refinery pipeline diagram

**Description:** Add to DOMAIN_NOTES.md a high-level pipeline diagram of the refinery: Triage → Extraction (A/B/C) → Chunking → PageIndex → Query. Use Mermaid or hand-drawn (photo/scan). Optionally include MinerU and Docling pipeline sketches for reference.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: specs/01-document-intelligence-refinery-system.md, plan §3.1

**Acceptance criteria:**
- DOMAIN_NOTES.md includes a pipeline diagram showing the five refinery stages in order.
- Diagram is readable and correctly represents the flow (Triage → Extraction → Chunking → PageIndex → Query).
- Optional: MinerU/Docling sketches are present or referenced.

---

## P0-T011 — Draft extraction strategy decision tree

**Description:** Add to DOMAIN_NOTES.md the draft extraction strategy decision tree (conceptual, no code). Include: root (document/DocumentProfile); Branch 1 — scanned_image or needs_vision_model → Strategy C; Branch 2 — native_digital and single_column → try A, escalate to B if confidence &lt; threshold; Branch 3 — else → Strategy B; Post–B escalation to C if confidence low; leaves (A/B/C output or “all strategies exhausted”). List which thresholds or signals remain to be set empirically (e.g. confidence threshold, character count per page, image area ratio).

**Files:**
- `DOMAIN_NOTES.md`
- Reference: plan §3.2, specs (e.g. triage, extraction engine)

**Acceptance criteria:**
- DOMAIN_NOTES.md contains the full decision tree with branches for A, B, C and escalation.
- Open thresholds / empirical parameters are explicitly listed.
- Tree is clearly labeled as draft and suitable for refinement in Phase 1–2.

---

## P0-T012 — Failure modes per document class and decision boundary heuristics

**Description:** For each target document class (A–D), document in DOMAIN_NOTES.md what goes wrong or would go wrong with naive extraction (e.g. Class A: tables broken, multi-column order; Class B: no text layer, need OCR/VLM; Class C: mixed layout; Class D: table fidelity). Add a short “Decision boundary heuristics” summary: when is “character count &gt; 100 per page” or “image area &lt; 50%” sufficient? When do we need layout or vision? Note uncertainties.

**Files:**
- `DOMAIN_NOTES.md`
- Reference: The Document Intelligence Refinery Guide (corpus description), plan §3.1 and §4

**Acceptance criteria:**
- DOMAIN_NOTES.md describes failure modes or risks for each document class (A–D) where such documents are available.
- “Decision boundary heuristics” (or equivalent) subsection summarizes when fast text vs. layout vs. vision is needed and what remains uncertain.
- Evidence aligns with Phase 0 acceptance checks (failure modes per class, decision tree, pipeline diagram).

---

## Phase 0 completion

When all tasks P0-T001 through P0-T012 are done and their acceptance criteria met, the Phase 0 acceptance checks in the plan (§4) are satisfied: MinerU understood, Docling understood, pdfplumber metrics, chunking risks, failure modes per class, decision tree, and pipeline diagram are all present in DOMAIN_NOTES.md.
