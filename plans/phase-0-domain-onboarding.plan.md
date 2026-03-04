# Phase 0: Domain Onboarding — Plan

**Source:** Implementation Curriculum, *The Document Intelligence Refinery Guide* (reference-docs).  
**Target:** Phase 0 — Domain Onboarding / Document Science Primer.  
**Output:** Understanding that constrains system design; no code.

---

## 1. Goal

**What we learn:** The problem domain of document intelligence: how PDFs differ (native vs. scanned), how extraction strategies differ (fast text vs. layout vs. vision), and why naive extraction and chunking fail. We learn the **decision boundaries** that will drive triage and extraction routing, and the **failure modes** that the pipeline must handle or degrade gracefully.

**Why it constrains system design:**

- **Triage and routing** depend on signals we validate in Phase 0 (character density, whitespace, image ratio, table presence). Thresholds chosen here feed `extraction_rules.yaml` and DocumentProfile logic.
- **Extraction strategy selection** (A / B / C) is only defensible if we have evidence for when fast text is sufficient vs. when layout or vision is required. Phase 0 produces that evidence per document class.
- **Chunking and provenance** requirements are grounded in observed failures (tables flattened, reading order wrong, no bbox). The LDU and ExtractedDocument schemas must support what we learn about structure loss.
- **Escalation guard** (no low-confidence output downstream) is a direct response to “garbage in, hallucination out”; Phase 0 makes concrete which documents or pages are “low confidence” so we can set gates.

Without Phase 0, we risk hardcoding wrong thresholds, under-escalating (bad extraction) or over-escalating (unnecessary cost), and designing schemas that don’t match real extraction outputs.

---

## 2. Experiments

### 2.1 MinerU architecture understanding

**Objective:** Understand MinerU’s pipeline (pipeline vs. VLM vs. hybrid), stages, and intermediate artifacts so we can evaluate it as a Strategy B (layout-aware) option and design adapters if we use it.

**Activities:**

- Read MinerU architecture documentation end-to-end. Capture: PDF-Extract-Kit → Layout Detection → Formula/Table Recognition → Markdown export (or equivalent current pipeline).
- Identify: which stages use classical CV/heuristics vs. neural layout models vs. VLM. Map “pipeline” (deterministic/multi-model) vs. “VLM” (single vision-language model) vs. “hybrid” (e.g. layout model + VLM for tables).
- Document intermediate artifacts: e.g. layout bboxes, table regions, cell grids, formula masks. These inform what we can normalize into ExtractedDocument (text blocks, tables, figures, reading order).
- Draw the pipeline (on paper or Mermaid): inputs, stages, outputs, and where structure is added or lost.

**Outcome:** A short written summary (for DOMAIN_NOTES.md) of MinerU’s architecture, where it fits in the refinery (Strategy B), and what adapter work would be needed to produce our ExtractedDocument schema.

---

### 2.2 Docling unified representation model (DoclingDocument)

**Objective:** Understand Docling’s Document Representation Model—how structure, text, tables, and figures are encoded in a single traversable object—so we can extend or wrap it as our normalized extraction schema.

**Activities:**

- Study Docling’s DoclingDocument (or equivalent) schema: top-level structure, how text blocks, tables, figures, and reading order are represented.
- Identify: presence of bbox and page for every element; table representation (headers, rows, cells); figure + caption binding; reading order or equivalent.
- Map DoclingDocument fields to our ExtractedDocument logical schema (text_blocks, tables, figures, reading_order). Note gaps (e.g. no reading_order, or different bbox format).
- Run Docling on the same provided documents used for pdfplumber (see below). Inspect output structure and quality.

**Outcome:** A mapping (for DOMAIN_NOTES.md) from DoclingDocument to ExtractedDocument; notes on “wrap vs. adapt”; comparison of Docling output quality vs. MinerU on the same docs (qualitative).

---

### 2.3 pdfplumber: bbox coordinates and character density / whitespace ratio metrics

**Objective:** Establish the signals and coordinate system we will use for triage (origin_type, layout_complexity) and for Strategy A confidence scoring. Every extracted fact must carry bbox and page; we need to understand how pdfplumber exposes these and what metrics we can compute.

**Activities:**

- Install pdfplumber and run it on the **provided documents** (or a representative subset: at least one per class A–D if available).
- **Bbox coordinates:** Document how bbox is reported (e.g. per character, per line, per word). Understand coordinate system (origin, units). Determine how to serialize bbox for audit (e.g. per LDU or per block). Note any limitations (e.g. no bbox for embedded images).
- **Character density:** Compute characters per page (or per unit area). Compare native digital vs. scanned (expect scanned to have zero or near-zero character count if no OCR). Record typical ranges per document class.
- **Whitespace ratio:** Compute fraction of page area that is “empty” or low-density. Relate to layout (multi-column, table-heavy) and to scan vs. digital.
- **Additional signals:** Image area ratio (if available), font metadata presence. Document how these differ across document classes.
- Capture sample numbers and distributions (e.g. “Class A: char count 800–3000/page; Class B: 0 or OCR-dependent”). These inform threshold design for “meaningful character stream” and “image area must not dominate.”

**Outcome:** A concise report in DOMAIN_NOTES.md: how bbox works in pdfplumber, how we’ll use it for provenance; table or ranges for character density, whitespace ratio (and any other metrics) by document class; and implications for triage and Strategy A confidence gates.

---

### 2.4 Chunking risks: tables, multi-column, headings

**Objective:** Ground the Semantic Chunking Engine and LDU rules in concrete failure modes. Understand why token-count chunking fails for tables, multi-column order, and section headings.

**Activities:**

- **Tables:** On a sample document (e.g. financial report), extract text with pdfplumber only (no layout). Observe: are tables flattened into lines? Are headers separated from cells? Simulate a 512-token chunk boundary through a table and note what is severed. Document: “A 512-token chunk that bisects a financial table produces hallucinations” with a concrete example.
- **Multi-column:** On a multi-column document, extract raw text in default order. Compare reading order to visual order. Document where order is wrong and how that would break “section” or “list” semantics if we chunk by position.
- **Headings:** Identify how headings appear in raw extraction (font size, style, numbering). Note: without layout, can we reliably detect section boundaries? Document risk of missing or wrong section boundaries and impact on parent_section and PageIndex.
- Optional: Run a layout-aware tool (Docling or MinerU) on the same docs and compare: do we get correct table structure and reading order? This reinforces “when to use Strategy B.”

**Outcome:** A “Chunking risks” subsection in DOMAIN_NOTES.md: tables (header/cell split), multi-column (order), headings (detection and section boundaries), with short examples. This justifies the five chunking rules and the need for structure-preserving LDUs.

---

## 3. Outputs

### 3.1 DOMAIN_NOTES.md outline

The deliverable is **DOMAIN_NOTES.md** with at least the following content (outline). Filling it is the outcome of the experiments above.

1. **Pipeline diagram**  
   - High-level refinery pipeline (Mermaid or hand-drawn): Triage → Extraction (A/B/C) → Chunking → PageIndex → Query.  
   - Optional: MinerU and Docling pipeline sketches for reference.

2. **Extraction strategy decision tree (draft)**  
   - Conceptual tree: when to use Strategy A vs. B vs. C.  
   - Based on origin_type, layout_complexity, and confidence.  
   - (Detailed tree is in §3.2 below.)

3. **Failure modes observed**  
   - **Per document class (A–D):** For each class, document what went wrong or what would go wrong with naive extraction (e.g. Class A: tables broken, multi-column order; Class B: no text layer, need OCR/VLM; Class C: mixed layout; Class D: table fidelity).  
   - **Decision boundary heuristics:** When is “character count > 100 per page” or “image area < 50%” sufficient? When do we need layout or vision? Short summary of heuristics and uncertainties.

4. **MinerU and Docling notes**  
   - Architecture summary (pipeline vs. VLM vs. hybrid).  
   - DoclingDocument → ExtractedDocument mapping and adapter implications.  
   - Quality comparison on provided documents (qualitative).

5. **pdfplumber and metrics**  
   - Bbox coordinates: how they work, how we’ll use them for provenance.  
   - Character density, whitespace ratio (and any other metrics): typical values by class, implications for thresholds.

6. **Chunking risks**  
   - Tables, multi-column, headings (as in §2.4).  
   - Why token-boundary chunking is unacceptable and how this constrains LDU design.

### 3.2 Draft extraction strategy decision tree (conceptual)

Produce a **draft** extraction strategy decision tree. It should be conceptual (no code), suitable to refine later in Phase 1–2. Suggested structure:

- **Root:** Input = document (or DocumentProfile from triage).
- **Branch 1:** If `origin_type == scanned_image` OR `estimated_extraction_cost == needs_vision_model` → use **Strategy C** (vision). No A/B attempt for scanned docs.
- **Branch 2:** Else if `origin_type == native_digital` AND `layout_complexity == single_column` → try **Strategy A** (fast text).  
  - If Strategy A **confidence ≥ threshold** → emit A output.  
  - Else → **escalate to Strategy B** (do not emit A output).
- **Branch 3:** Else (multi_column, table_heavy, figure_heavy, mixed) → use **Strategy B** (layout) directly.
- **Post–Strategy B:** If B is used and confidence is below threshold → escalate to **Strategy C**.
- **Leaves:** Strategy A output, Strategy B output, Strategy C output, or “all strategies exhausted” (failure).

Document in DOMAIN_NOTES.md: (1) this tree, and (2) which thresholds or signals are still to be set empirically (e.g. confidence threshold, character count per page, image area ratio).

---

## 4. Acceptance checks

Phase 0 is complete when the following evidence exists:

| Check | Evidence |
|-------|----------|
| **MinerU understood** | DOMAIN_NOTES.md contains an architecture summary (pipeline vs. VLM vs. hybrid) and a pipeline diagram or sketch. |
| **Docling understood** | DOMAIN_NOTES.md contains a description of DoclingDocument and a mapping (or gap list) to ExtractedDocument; Docling has been run on provided documents and output inspected. |
| **pdfplumber metrics** | DOMAIN_NOTES.md documents bbox usage and at least character density and whitespace ratio (and any other chosen metrics) with observations on provided documents. |
| **Chunking risks** | DOMAIN_NOTES.md documents risks for tables, multi-column, and headings with concrete examples or observations. |
| **Failure modes per class** | DOMAIN_NOTES.md describes failure modes or risks for each target document class (A–D) where such documents are available. |
| **Decision tree** | A draft extraction strategy decision tree is in DOMAIN_NOTES.md with branches for A/B/C and escalation; open thresholds are noted. |
| **Pipeline diagram** | DOMAIN_NOTES.md includes a pipeline diagram (Mermaid or hand-drawn) of the refinery (and optionally MinerU/Docling). |

No code is required. All deliverables are documentation and conceptual artifacts that constrain and inform Phases 1–4.
