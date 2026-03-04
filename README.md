# Document Intelligence Refinery

Pipeline: triage → extraction (multi-strategy, confidence-gated) → chunking → PageIndex → query with provenance. Aligns with *The Document Intelligence Refinery Guide* §8 deliverables.

## Setup

Use **uv** only (no pip). Sync dependencies:

```bash
uv sync
```

## Run tests

```bash
uv run pytest
```

## Configuration

- **Vision (Strategy C):** Provider and API key are configurable via **`.env`** so you can switch (e.g. to Gemini) without code changes. Copy `.env.example` to `.env` and set:
  - `REFINERY_VISION_PROVIDER` — `openai` or `google`
  - `REFINERY_VISION_API_KEY` — key value, or
  - `REFINERY_VISION_API_KEY_ENV` — name of the env var that holds the key (e.g. `GEMINI_API_KEY`)
- A `.env` file in the project root or cwd is loaded automatically. See [spec 03 §6.4](specs/03-multi-strategy-extraction-engine.md#64-model-selection-and-api-configuration).

## Run

- **Triage** (classify a PDF, write DocumentProfile to `.refinery/profiles/`):
  ```bash
  uv run python -m src.main --pdf path/to/document.pdf
  ```
- **Character density analysis** (single PDF: character density, bbox distributions, whitespace ratios):
  ```bash
  uv run python scripts/run_character_density_analysis.py path/to/document.pdf
  ```
  Optional: write full JSON with `-o report.json`.
- **Docling** (run Docling on a single PDF; export to Markdown and/or JSON). Requires `pip install docling`:
  ```bash
  uv run python scripts/run_docling.py path/to/document.pdf
  ```
  Optional: `-o <dir>` writes `<name>.md` and `<name>.json` in that directory; `-o file.md` or `-o file.json` writes a single format.
- **Extraction** and other stages are invoked programmatically or via additional entrypoints (see `src/agents/`, `src/strategies/`).