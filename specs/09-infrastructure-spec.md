# Spec: Infrastructure — Containerization, Entrypoints & Persisted Artifacts

**Parent spec:** [01 – Document Intelligence Refinery System](01-document-intelligence-refinery-system.md)  
**Related:** [08 – Data Layer](08-data-layer-spec.md) (paths for FactTable, vector store), [05 – PageIndex Builder](05-pageindex-builder-spec.md) (pageindex path), [06 – Query Agent](06-query-agent-and-provenance-spec.md) (query interface).  
**Constitution alignment:** Config-over-code; reproducible runs; all pipeline artifacts persist under a single mountable directory so the refinery can run in a container and state survives across invocations.

---

## 1. Purpose

This spec defines how the Document Intelligence Refinery is **containerized** and **run** so that:

- A single image can execute any pipeline stage (triage, extract, chunk, index, query) via well-defined entrypoints.
- Dependencies are installed in a reproducible way using **uv** (no pip for package management).
- All artifacts that must survive across runs (profiles, extraction output, LDUs, PageIndex, FactTable, vector store) are clearly specified and can be mounted or persisted outside the container.

It does not prescribe orchestration (e.g. Kubernetes, Compose) or hosting; it defines the **Dockerfile requirements**, **entrypoints**, and **artifact layout** that any deployment must respect.

---

## 2. Dockerfile Requirements

The build must produce an image that runs the refinery with uv as the sole package manager. The following are **requirements** for the Dockerfile (or equivalent container build).

### 2.1 Base image

- **Requirement:** Use an official or maintained **Python** base image (e.g. `python:3.12-slim` or `python:3.11-slim`). The image must provide a supported Python version compatible with the project’s `pyproject.toml` (e.g. Python 3.11+).
- **Rationale:** Slim variants keep image size down; the refinery is CPU-bound for chunking and may call external APIs for extraction/LLM; no GPU is required in the base unless a specific model demands it (out of scope for this spec).
- **Optional:** Multi-stage build to copy only runtime artifacts into the final stage; optional if a single stage is sufficient for size and security.

### 2.2 uv install and sync

- **Requirement:** Install **uv** in the container (e.g. from the official install script or package). The project must **not** rely on pip for installing the refinery or its dependencies (constitution: uv-only).
- **Requirement:** Copy the project’s `pyproject.toml` and `uv.lock` (and any `pyproject.toml`-referenced source) into the image, then run **uv sync** (or equivalent) so that the locked environment is reproduced. No `pip install -e .` or unpinned `pip install` of the project.
- **Requirement:** The working directory for the application must be set so that `uv run` can resolve the project (e.g. `WORKDIR` set to the directory containing `pyproject.toml`). All pipeline commands (triage, extract, chunk, index, query) must be invoked via **uv run** (e.g. `uv run python -m ...` or `uv run <cli>`) so that the locked environment is used.
- **Optional:** Install only production dependencies in the image if the project declares optional dev dependencies; tests may run in a separate build or host.

### 2.3 Entrypoints

- **Requirement:** The image must support the following **logical entrypoints**. Each entrypoint runs one pipeline stage (or a single command) so that a scheduler or user can run triage-only, extract-only, chunk-only, index-only, or query-only, or a full pipeline by chaining invocations.
- **Mechanism:** Entrypoints may be implemented as:
  - **Default or secondary process:** e.g. `CMD` or `ENTRYPOINT` that accepts a first argument (e.g. `triage`, `extract`, `chunk`, `index`, `query`) and dispatches to the corresponding module/script; or
  - **Multiple named commands:** e.g. scripts or wrappers invoked as `uv run python -m src.agents.triage ...`, `uv run python -m src.agents.extractor ...`, etc., with the container started with the desired command override.
- **Required entrypoints (logical):**

  | Entrypoint | Purpose | Typical invocation (conceptual) |
  |------------|---------|--------------------------------|
  | **triage** | Run Stage 1 (Triage Agent) on input document(s). | Consumes path(s) or list of documents; writes DocumentProfile(s) and updates extraction ledger as needed. |
  | **extract** | Run Stage 2 (Multi-Strategy Extraction). | Consumes DocumentProfile / document path; produces ExtractedDocument; writes extraction ledger. |
  | **chunk** | Run Stage 3 (Semantic Chunking Engine). | Consumes ExtractedDocument; produces LDUs; may run ChunkValidator. |
  | **index** | Run Stage 4 (PageIndex Builder) and optional LDU ingestion (vector store, FactTable extractor). | Consumes LDUs; builds PageIndex tree; persists PageIndex JSON; optionally ingests LDUs into vector store and runs FactTable extraction. |
  | **query** | Run Stage 5 (Query Interface Agent). | Consumes query (and optional document scope); uses PageIndex, vector store, FactTable; returns answer + ProvenanceChain. |

- **Full pipeline:** A single entrypoint that runs triage → extract → chunk → index (and optionally query) in sequence is optional; the spec requires at least the five separate entrypoints so that stages can be run independently (e.g. re-chunk without re-extract, or query only).
- **Environment and config:** Entrypoints must respect configuration (e.g. env vars or config files) for paths (e.g. `.refinery` base, FactTable path, vector store path) so that the same image can be used with different mounts. No hardcoded absolute paths inside the image for artifact locations that are intended to be mounted.

---

## 3. Running Stages in the Container

### 3.1 General

- **Inputs:** Document(s) and/or corpus state (profiles, extracted documents, LDUs) must be available to the container via **mounted volumes** or injected paths. The spec assumes the host (or orchestrator) mounts a directory that becomes the refinery’s **data root** (e.g. `.refinery` or a configurable base).
- **Outputs:** Each stage writes its outputs under that same data root (or configured paths) so that outputs persist on the host and are visible to subsequent runs (e.g. same or another container).
- **Invocation:** The user (or orchestrator) runs the container with the appropriate **command** (overriding the default if any) to select the entrypoint (triage, extract, chunk, index, query), plus any arguments (e.g. document path, query string). Example pattern: `docker run ... <image> <entrypoint> <args>`.

### 3.2 Triage (Stage 1)

- **Purpose:** Classify document(s) and produce DocumentProfile(s).
- **Input:** Path to document(s) (e.g. PDF) or a list of paths; may be under a mounted input directory.
- **Output:** DocumentProfile(s) written under the refinery data root (e.g. `.refinery/profiles/{document_id}.json`); extraction ledger may be updated.
- **How to run in container:** Start container with entrypoint **triage** and arguments pointing to the document path(s) inside the container (e.g. `/data/input/doc.pdf` where `/data/input` is a mount). The process reads the document(s), runs the Triage Agent, and writes profiles (and optionally ledger) to the mounted artifact directory (e.g. `/data/refinery` → `.refinery` on host).

### 3.3 Extract (Stage 2)

- **Purpose:** Run multi-strategy extraction; produce ExtractedDocument(s).
- **Input:** DocumentProfile (from triage) and document path; or document path with on-the-fly triage. Reads extraction rules and ledger from the artifact directory.
- **Output:** ExtractedDocument(s) (in-memory or persisted as implementation-defined); extraction ledger updated (e.g. `.refinery/extraction_ledger.jsonl`).
- **How to run in container:** Start container with entrypoint **extract** and arguments (e.g. document path or document_id). Process reads profile and document, runs extraction, writes ledger and any persisted extraction output to the mounted artifact directory.

### 3.4 Chunk (Stage 3)

- **Purpose:** Convert ExtractedDocument(s) into LDUs; run ChunkValidator.
- **Input:** ExtractedDocument(s) (from extract stage or from persisted intermediate); config (e.g. max_tokens, chunking rules).
- **Output:** List of LDUs (in-memory or persisted); no change to FactTable or vector store at this stage.
- **How to run in container:** Start container with entrypoint **chunk** and arguments (e.g. document_id or path to extracted document). Process reads extraction output, runs Chunking Engine and ChunkValidator, writes or streams LDUs. LDUs may be written to a known path under the artifact directory for consumption by **index**, or passed in-memory in a combined pipeline; the spec requires that the **index** stage can consume LDUs (from disk or prior step).

### 3.5 Index (Stage 4 + data layer)

- **Purpose:** Build PageIndex from LDUs; optionally ingest LDUs into the vector store and run FactTable extraction.
- **Input:** LDUs (from chunk stage or from persisted intermediate); document_id and page_count.
- **Output:** PageIndex JSON per document (e.g. `.refinery/pageindex/{document_id}.json`); optionally vector store updated (ChromaDB under `.refinery/vector_store/`); optionally FactTable updated (`.refinery/fact_table.db`).
- **How to run in container:** Start container with entrypoint **index** and arguments (e.g. document_id or path to LDUs). Process reads LDUs, builds PageIndex tree, persists PageIndex; if configured, ingests LDUs into ChromaDB and runs the FactTable extractor writing to SQLite. All outputs go to the mounted artifact directory so they persist.

### 3.6 Query (Stage 5)

- **Purpose:** Answer natural-language questions (or run audit mode) using PageIndex, vector store, and FactTable.
- **Input:** Query string (and optional document scope); reads PageIndex files, vector store, and FactTable from the artifact directory.
- **Output:** Answer text plus ProvenanceChain (and optional verification_status for audit); typically returned to the caller (stdout, API response, or file).
- **How to run in container:** Start container with entrypoint **query** and arguments (e.g. query string, optional document_ids). Process reads from the mounted artifact directory (PageIndex, vector store, FactTable, document registry for names), runs the Query Agent, and returns the response. For interactive or API use, the container may expose a long-running process (e.g. HTTP server) instead of one-shot; the spec treats one-shot query as the minimum contract.

---

## 4. Artifacts to Mount and Persist

All of the following must be **mountable** into the container and **persisted** on the host (or persistent volume) so that state is not lost when the container is removed. The canonical layout is under a single **refinery data root** (e.g. `.refinery` or a configurable path such as `/data/refinery`).

### 4.1 Directory: refinery data root (e.g. `.refinery/`)

- **Purpose:** Root for all pipeline artifacts except where a separate path is explicitly used (e.g. some deployments may put FactTable or vector store elsewhere via config).
- **Must be mounted:** Yes. The container must receive this directory as a volume mount so that profiles, ledger, pageindex, and (unless overridden) FactTable and vector store are readable and writable.
- **Contents (logical):**

  | Path / artifact | Producer | Consumer | Description |
  |-----------------|----------|----------|-------------|
  | **profiles/** | Triage | Extract | DocumentProfile per document: `profiles/{document_id}.json`. |
  | **extraction_ledger.jsonl** | Extract | Triage/Extract (audit), optional reporting | One line per extraction run (document_id, strategy, confidence, etc.). |
  | **pageindex/** | Index (PageIndex Builder) | Query (pageindex_navigate) | One PageIndex JSON per document: `pageindex/{document_id}.json`. |
  | **ExtractedDocument / LDUs** | Extract, Chunk | Chunk, Index | Intermediate artifacts; exact paths (e.g. `extraction/`, `ldus/`) are implementation-defined. If persisted to disk, they must live under the data root or a configured path so they can be mounted. |

- **Invariant:** Any stage that reads or writes profiles, ledger, or pageindex must use the same data root (via config or env) so that a single mount point suffices.

### 4.2 SQLite database: FactTable

- **Canonical path:** `.refinery/fact_table.db` (or configurable, e.g. `data_dir/fact_table.db` per [08 – Data Layer](08-data-layer-spec.md)).
- **Must be mounted or persisted:** Yes. The FactTable is the sole SQLite file for facts; it is written by the FactTable extractor (during **index** or a dedicated step) and read by the Query Agent (**structured_query**). The file must reside on a volume that persists across container restarts.
- **Mount recommendation:** Either mount the refinery data root (so `.refinery/fact_table.db` is inside the mount) or mount a dedicated volume for the database file and set the path via configuration so the container writes to the mounted path.

### 4.3 Vector store: ChromaDB

- **Canonical path:** `.refinery/vector_store/` (or configurable per [08 – Data Layer](08-data-layer-spec.md)). ChromaDB stores its files (e.g. SQLite, embedding files) under this directory.
- **Must be mounted or persisted:** Yes. The vector store is written during **index** (LDU ingestion) and read during **query** (semantic_search). The entire directory must persist so that re-running the container sees the same embeddings and metadata.
- **Mount recommendation:** Mount the refinery data root so that `vector_store/` is inside it, or mount a dedicated volume for `vector_store/` and set the path via configuration.

### 4.4 Input documents (optional mount)

- **Purpose:** PDFs (or other inputs) to be triaged, extracted, and chunked. They may be read from a separate mount (e.g. `/input` or `/data/documents`) so the image does not bundle documents. Paths passed to **triage** / **extract** / **chunk** must be valid inside the container (i.e. under a mounted path).
- **Must be mounted:** Only if documents are not baked into the image (typical). For production, documents are mounted or streamed in; the spec does not require a specific input path, only that the entrypoints accept document path(s) and that those paths are accessible inside the container.

### 4.5 Configuration files (optional)

- **Purpose:** Extraction rules, chunking rules, query agent config (e.g. `extraction_rules.yaml`, `chunking_rules.yaml`). May live in the repo (baked into the image) or be mounted so that the same image can be used with different rules.
- **Mount:** Optional; if config is mounted, a path such as `/config` or under the data root can be used and referenced via env or CLI.

---

## 5. Summary: What Must Be Mounted / Persisted

| Artifact | Path (canonical) | Required mount/persist | Used by |
|----------|------------------|-------------------------|---------|
| **Refinery data root** | `.refinery/` (or configured base) | Yes | All stages |
| **Profiles** | `.refinery/profiles/` | Yes (as part of root) | Triage (write), Extract (read) |
| **Extraction ledger** | `.refinery/extraction_ledger.jsonl` | Yes (as part of root) | Extract (write), optional audit |
| **PageIndex** | `.refinery/pageindex/{document_id}.json` | Yes (as part of root) | Index (write), Query (read) |
| **FactTable** | `.refinery/fact_table.db` | Yes | Index / extractor (write), Query (read) |
| **Vector store** | `.refinery/vector_store/` | Yes | Index (write), Query (read) |
| **Input documents** | Implementation-defined (e.g. `/input`) | If not in image | Triage, Extract, Chunk |
| **Config files** | Repo or mounted path | Optional (mount for overrides) | All stages |

**Invariant:** A single volume mount for the refinery data root (e.g. `-v /host/refinery:/app/.refinery`) must be sufficient to persist profiles, ledger, pageindex, FactTable, and vector store, provided the implementation places them under that root (or config points to paths under that mount). If FactTable or vector store are configured to live outside the root, they require separate mounts or a parent mount that includes those paths.

---

**Version:** 1.0  
**Spec status:** Spec only; no code. Implementation must provide a Dockerfile (or equivalent) and entrypoints that satisfy this spec.
