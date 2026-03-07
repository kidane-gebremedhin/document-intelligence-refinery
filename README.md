# Document Intelligence Refinery

Pipeline: triage → extraction (multi-strategy, confidence-gated) → chunking → PageIndex → query with provenance. Aligns with *The Document Intelligence Refinery Guide* §8 deliverables.

**Query Agent & Provenance Layer:** A three-tool LangGraph agent (`pageindex_navigate`, `semantic_search`, `structured_query`) answers natural-language questions. Every answer includes a **ProvenanceChain**: source citations with `document_name`, `page_number`, `bbox`, and `content_hash`. A **FactTable** extractor pulls key-value facts (e.g. revenue, date, period) from tables and paragraph/list LDUs into SQLite for precise querying. **Audit mode** verifies a claim against the corpus and either returns verified citations or flags the claim as not found / unverifiable.

## Setup

Use **uv** only (no pip). Sync dependencies:

```bash
uv sync
```

Optional extras (e.g. dev deps for tests):

```bash
uv sync --extra dev
```

## Configuration

- **Vision (Strategy C):** Provider and API key are configurable via **`.env`**. Copy `.env.example` to `.env` and set:
  - `REFINERY_VISION_PROVIDER` — `openai` or `google`
  - `REFINERY_VISION_API_KEY` — key value, or
  - `REFINERY_VISION_API_KEY_ENV` — name of the env var that holds the key (e.g. `GEMINI_API_KEY`)
- A `.env` file in the project root or cwd is loaded automatically. See [spec 03 §6.4](specs/03-multi-strategy-extraction-engine.md#64-model-selection-and-api-configuration).
- **RAG-like semantic search:** The vector store uses deterministic (hash) embeddings by default. For real semantic retrieval (query and audit), set `REFINERY_EMBEDDING_MODEL` in `.env` (e.g. `all-MiniLM-L6-v2`), install sentence-transformers (`uv sync --extra semantic`), then re-run the pipeline so LDUs are re-ingested with the new embeddings. Query and audit then use embedding similarity instead of word matching.
- **PageIndex LLM summarization:** When `REFINERY_VISION_PROVIDER` and API key are set (openai or google), section summaries are generated and stored in `.refinery/pageindex/{document_id}.json`. Improves PageIndex topic scoring for query accuracy.
- **LangSmith tracing:** To trace query-agent and audit runs to [LangSmith](https://smith.langchain.com), set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`. Optionally set `LANGSMITH_PROJECT` to name the project. Scripts load `.env` before running.

## Running the application

### Triage (Stage 1)

Classify a PDF and print a `DocumentProfile` as JSON:

```bash
uv run python -m src.main --pdf path/to/document.pdf
```

Optional: `-v` / `--verbose` for debug logging. To persist profiles to `.refinery/profiles/`, redirect output to a file or use the generator script (see below).

### Scripts

| Command | Description |
|---------|-------------|
| **Character density** | Per-page character density, bbox distributions, whitespace ratios |
| **Docling** | Layout-aware PDF → Markdown/JSON (Strategy B backend) |
| **Dump LDUs** | Run Stage 1–3 and write `.refinery/ldus/{document_id}.json` |
| **Run full pipeline** | Run all 5 stages and write `.refinery/` artifacts |
| **Query agent** | LangGraph agent (one question → answer + ProvenanceChain); see [Query & provenance](#query--provenance-phase-4) |
| **Inspect refinery data** | Print vector store (LDU count, document IDs, samples) and fact table (row count, sample rows); see [Inspecting the vector store and fact table](#inspecting-the-vector-store-and-fact-table) |

**Character density analysis** (single PDF):

```bash
uv run python scripts/run_character_density_analysis.py path/to/document.pdf
```

Optional: `-o report.json` to write full JSON.

**Docling** (single PDF; requires `docling` from `uv sync`):

```bash
uv run python scripts/run_docling.py path/to/document.pdf
```

Optional: `-o <dir>` writes `<name>.md` and `<name>.json` in that directory; `-o file.md` or `-o file.json` writes a single format. Use `-n 5` to limit pages (e.g. for large scanned PDFs).

Writes `.refinery/profiles/*.json` and `.refinery/extraction_ledger.jsonl` without running triage/extraction (useful when the pipeline is slow or stalled).

**Dump LDUs** (Stage 1–3: triage → extraction → chunking):

```bash
uv run python scripts/dump_ldus.py path/to/document.pdf --limit 25
```

Writes `.refinery/ldus/{document_id}.json` and prints a preview of LDUs (id, type, pages, content_hash, snippet).

**Run full pipeline** (Stages 1–5: triage → extraction → chunking → PageIndex → ingest):

```bash
uv run python scripts/run_pipeline.py path/to/document.pdf
```

Writes artifacts under `.refinery/`:

- `.refinery/profiles/{document_id}.json`
- `.refinery/ldus/{document_id}.json`
- `.refinery/pageindex/{document_id}.json`
- `.refinery/vector_store/` (ChromaDB)
- `.refinery/fact_table.db`
- `.refinery/extraction_ledger.jsonl`

### Extraction (Stage 2)

Extraction is invoked programmatically. Use `ExtractionRouter` from `src.agents` with a `DocumentProfile` (e.g. from triage or loaded from `.refinery/profiles/{document_id}.json`). See `src/agents/extractor.py` and `src/strategies/` for the multi-strategy pipeline and escalation logic.

### Query & provenance (Phase 4)

**Vector store** — Ingest LDUs and run a semantic query (ChromaDB under `.refinery/vector_store/`):

Ingests the LDUs, runs one search, and prints the top hit with provenance fields (document_id, ldu_id, page_refs, content_hash).

**Audit mode** — Verify a claim against the corpus; returns either **verified** (with source citations: document_name, page_number, bbox, content_hash) or **not found / unverifiable**:

```bash
uv run python scripts/run_audit.py "The report states revenue was $4.2B in Q3"
uv run python scripts/run_audit.py "Revenue was $4.2B" --refinery-dir .refinery --document-id <document_id>
```

Options: `--refinery-dir`, `--document-id`, `--document-names`. Ensure the refinery is populated first (e.g. run the pipeline or demo).

**LangGraph query agent** — One question through the agent (pageindex_navigate, semantic_search, structured_query); answer + ProvenanceChain. See [Run LangGraph pipeline end-to-end](#run-langgraph-pipeline-end-to-end) below.

```bash
uv run python scripts/run_query_agent.py "What was revenue in Q3?"
uv run python scripts/run_query_agent.py   # prompts for a question
```

Options: `--refinery-dir` (default `.refinery`), `--document-id` (restrict to one doc), `--top-k`, `--document-names <path>` (JSON map of document_id → display name). No sample data: use data produced by the pipeline.

### Run LangGraph pipeline end-to-end

1. **Populate the refinery** (vector store, PageIndex, fact table) by running the full pipeline on one or more PDFs:

   ```bash
   uv run python scripts/run_pipeline.py path/to/document.pdf
   ```

   This writes `.refinery/vector_store/`, `.refinery/pageindex/`, `.refinery/fact_table.db`, and related artifacts.

2. **Run the query agent** with a natural-language question (paths default to `.refinery/`):

   ```bash
   uv run python scripts/run_query_agent.py "What was revenue in Q3?"
   ```

   Optionally restrict to one document and/or override paths:

   ```bash
   uv run python scripts/run_query_agent.py "Summarize the risks." --document-id <document_id>
   uv run python scripts/run_query_agent.py "Summarize the risks." --refinery-dir /path/to/.refinery
   ```

   Optional display names: create `.refinery/document_names.json` with `{"<document_id>": "Report.pdf"}` (or pass `--document-names <path>`). The script prints the answer and a **ProvenanceChain** with each citation’s document_name, page_number, bbox, and content_hash.

### Run the Refinery with a custom document path and custom query

To run the pipeline in the exact 4-step sequence and then ask a question (answer + ProvenanceChain with page and bounding box citations), use the demo script with your **document path** and optional **query**:

**Step 1: Triage** → DocumentProfile output  
**Step 2: Extraction** → Extract and chunk to LDUs  
**Step 3: PageIndex** → Build page index and ingest (vector store + FactTable)  
**Step 4: Query with Provenance** → Your question → answer + ProvenanceChain (page_number + bbox)

```bash
# Custom document path + custom query (all in one run)
uv run python scripts/run_refinery_demo.py path/to/your/document.pdf "What was revenue in Q3?"
```

```bash
# Custom document path; question prompted after Step 3
uv run python scripts/run_refinery_demo.py path/to/your/document.pdf
```

```bash
# Custom output directory (default is .refinery)
uv run python scripts/run_refinery_demo.py path/to/document.pdf "Summarize the risks." --out /path/to/.refinery
```

The demo writes all artifacts under `--out` (default `.refinery/`) and prints the answer plus each citation’s `document_name`, `page_number`, `bbox`, and `content_hash`.

### Inspecting the vector store and fact table

To **check what’s in the vector store (ChromaDB)** and **fact table (SQLite)**:

**Using the inspect script (recommended):**

```bash
uv run python scripts/inspect_refinery_data.py
```

This prints total LDU count, document IDs, and sample entries from the vector store, plus total row count and sample rows from the fact table. Options:

- `--refinery-dir .refinery` — refinery directory (default: `.refinery`)
- `--vector-limit 5` — max sample LDUs to show (default: 10)
- `--fact-limit 20` — max fact rows to show (default: 20)
- `--vector-only` or `--fact-only` — inspect only one store

**Fact table only (SQLite):**

```bash
sqlite3 .refinery/fact_table.db "SELECT COUNT(*) FROM facts;"
sqlite3 .refinery/fact_table.db "SELECT document_id, entity, metric, value, period FROM facts LIMIT 10;"
```

**Vector store:** Data lives under `.refinery/vector_store/` (ChromaDB’s SQLite + embedding files). Use the inspect script above to list counts and sample documents without low-level ChromaDB usage.

## Tests

Run the test suite:

```bash
uv run pytest
```

Useful options:

- `-v` — verbose
- `-x` — stop on first failure
- `-k EXPR` — run tests matching `EXPR` (e.g. `-k triage`)

Example:

```bash
uv run pytest -v -k triage
```

## Project layout

- `src/agents/` — Triage agent, ExtractionRouter, **audit** (claim verification), **query_agent** (LangGraph, three tools)
- `src/chunking/` — **ChunkingEngine** (ExtractedDocument → LDUs) + validator (chunking constitution)
- `src/data/` — **Vector store** (ChromaDB), **FactTable** (SQLite), ingest & search
- `src/strategies/` — FastText (A), Layout (B), Vision (C) extractors
- `src/models/` — DocumentProfile, ExtractedDocument, LDU, PageIndex, ProvenanceChain, etc.
- `rubric/extraction_rules.yaml` — Config for triage and extraction thresholds
- `specs/` — Feature and system specs
