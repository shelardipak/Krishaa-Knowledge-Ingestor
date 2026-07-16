# Krishaa Knowledge Ingestor

A production-ready Python pipeline for ingesting product-support documents (PDFs and DOCX files) into [Qdrant Cloud](https://qdrant.tech) for use in RAG (Retrieval-Augmented Generation) systems. Built for Krishaa's electrical product knowledge base covering brands like Raychem, CharCoat, and Mennekes.

The pipeline handles the full ingestion lifecycle: document discovery → text/table/image extraction → embedding generation → vector storage, with incremental processing and optional image hosting via Supabase Storage.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running Ingestion](#running-ingestion)
- [CLI Reference](#cli-reference)
- [Data Models](#data-models)
- [Qdrant Point Structure](#qdrant-point-structure)
- [Incremental Ingestion](#incremental-ingestion)
- [Vendor Metadata Inference](#vendor-metadata-inference)
- [DOCX Handling](#docx-handling)
- [RAG Query Guide](#rag-query-guide)
- [Testing](#testing)
- [Tech Stack](#tech-stack)

---

## How It Works

```
knowledge/
    │
    ▼
1. DISCOVERY        recursive scan for .pdf and .docx files
    │
    ▼
2. MANIFEST CHECK   SHA-256 hash vs. ingestion_manifest.json → skip if unchanged
    │
    ▼
3. EXTRACTION       PDF: pdfplumber (text + tables) + PyMuPDF (images)
                    DOCX: python-docx (text + tables + embedded images)
    │
    ▼
4. IMAGE UPLOAD     [optional] PNG → Supabase Storage → public URL
    │
    ▼
5. EXTRACTION JSON  ExtractedDocument → data/processed/{slug}.{hash}.json
    │
    ▼
6. CHUNKING         RecursiveCharacterTextSplitter (tiktoken cl100k_base)
                    800 tokens / 120 token overlap
                    Chunk types: text, table, image_context
    │
    ▼
7. EMBEDDING        OpenAI text-embedding-3-small (1536 dims)
                    Batched 64 at a time, tenacity retry with exponential backoff
    │
    ▼
8. VECTOR UPSERT    Qdrant: deterministic uuid5 IDs, batched 64 at a time
                    Auto-creates collection + payload indexes
                    Deletes stale points from previous run
    │
    ▼
9. MANIFEST UPDATE  data/ingestion_manifest.json updated per document
```

---

## Repository Structure

```
Krishaa-Knowledge-Ingestor/
├── .env.example                     # Environment variable template
├── pyproject.toml                   # Package metadata and dependencies
│
├── knowledge/                       # Default source documents directory
│   ├── Charcoat_Catalogues/         # 33 PDFs — RTV coatings, joint fillers, etc.
│   ├── Mennekes_Catalogues/         # 8 PDFs — industrial plugs/sockets, EV charging
│   ├── Raychem_Catalogues/          # 35+ PDFs — cable joints, terminations, arresters
│   └── Other_Catalogues/            # 2 DOCX — FAQ / Q&A documents
│
├── data/                            # Runtime artifacts (gitignored)
│   ├── extracted_images/            # Locally saved images extracted from documents
│   ├── processed/                   # Normalized extraction JSON per document
│   └── ingestion_manifest.json      # Incremental ingestion state
│
├── src/rag_ingestion/               # Core package
│   ├── cli.py                       # Typer CLI — rag-ingest run
│   ├── config.py                    # Pydantic Settings loaded from .env
│   ├── discovery.py                 # Recursive file discovery
│   ├── models.py                    # Pydantic data models
│   ├── pipeline.py                  # End-to-end orchestration
│   ├── chunking.py                  # Token-aware document chunking
│   ├── embeddings.py                # OpenAI embedding generation
│   ├── manifest.py                  # Ingestion state tracker
│   ├── metadata.py                  # Source metadata inference
│   ├── storage.py                   # Supabase image upload
│   ├── vector_store.py              # Qdrant collection management + upsert
│   ├── logging_config.py            # Rich-based colored logging
│   ├── utils.py                     # SHA-256 hashing, slugify, batching utils
│   └── extractors/
│       ├── pdf.py                   # PdfExtractor (pdfplumber + PyMuPDF)
│       └── docx.py                  # DocxExtractor (python-docx + Pillow)
│
└── test/
    └── test.py                      # Manual semantic search test against Qdrant
```

---

## Prerequisites

- Python 3.11 or newer
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A [Qdrant Cloud](https://cloud.qdrant.io) cluster (or self-hosted Qdrant)
- A [Supabase](https://supabase.com) project with Storage enabled *(optional, required only for image upload)*

---

## Installation

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# 2. Install the package and all dependencies
pip install -e .

# 3. Set up your environment
cp .env.example .env
```

Edit `.env` with your API keys and service credentials before running.

---

## Configuration

All settings are read from `.env` via `pydantic-settings`. The full list of variables:

### Required

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key used for embedding generation |
| `QDRANT_URL` | Qdrant cluster endpoint URL |
| `QDRANT_API_KEY` | Qdrant API key (leave blank for unauthenticated local instances) |

### OpenAI

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Output vector dimensionality |

### Qdrant

| Variable | Default | Description |
|---|---|---|
| `QDRANT_COLLECTION` | `krishaa-collection` | Target collection name |
| `QDRANT_VECTOR_NAME` | `krishaa-dense-vector` | Named vector — required if your collection uses named vectors |
| `QDRANT_CHECK_COMPATIBILITY` | `false` | Qdrant SDK version compatibility check |

### Supabase Storage (optional)

| Variable | Default | Description |
|---|---|---|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Service role key for storage uploads |
| `SUPABASE_STORAGE_BUCKET` | `product-images` | Target storage bucket name |

### Local Paths

| Variable | Default | Description |
|---|---|---|
| `DOCUMENTS_DIR` | `knowledge` | Directory containing source PDF/DOCX files |
| `EXTRACTED_IMAGES_DIR` | `data/extracted_images` | Local directory for saved image files |
| `PROCESSED_DIR` | `data/processed` | Output directory for extraction JSON snapshots |
| `INGESTION_MANIFEST_PATH` | `data/ingestion_manifest.json` | Incremental state file |

### Chunking

| Variable | Default | Description |
|---|---|---|
| `CHUNK_SIZE_TOKENS` | `800` | Maximum tokens per chunk |
| `CHUNK_OVERLAP_TOKENS` | `120` | Overlap between consecutive chunks |

### Operational

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_BATCH_SIZE` | `64` | Number of chunks per OpenAI embedding request |
| `UPSERT_BATCH_SIZE` | `64` | Number of points per Qdrant upsert batch |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `DEFAULT_VENDOR` | `unknown_vendor` | Fallback vendor when not inferred from path |
| `DEFAULT_BRAND` | — | Fallback brand metadata |
| `DEFAULT_PRODUCT` | — | Fallback product metadata |
| `MIN_IMAGE_WIDTH` | `1` | Minimum pixel width to keep an extracted image |
| `MIN_IMAGE_HEIGHT` | `1` | Minimum pixel height to keep an extracted image |

---

## Running Ingestion

Place your PDF and DOCX files in the configured `DOCUMENTS_DIR` (default: `knowledge/`), then run:

```bash
# Basic run with metadata overrides
rag-ingest run --vendor krishaa --brand "Krishaa" --product "Support KB"

# Reprocess all files even if unchanged
rag-ingest run --force

# Process only the first document and stop on error
rag-ingest run --limit 1 --fail-fast

# Skip uploading images to Supabase (extract locally only)
rag-ingest run --skip-image-upload

# Combine options
rag-ingest run --vendor raychem --skip-image-upload --limit 10
```

You can also run the package directly:

```bash
python -m rag_ingestion run
```

Progress and per-document status are printed to the console via Rich logging.

---

## CLI Reference

```
rag-ingest run [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--force` | flag | `False` | Reprocess files even if their SHA-256 hash is unchanged |
| `--vendor TEXT` | string | — | Vendor name override applied to all files in this run |
| `--brand TEXT` | string | — | Brand name override |
| `--product TEXT` | string | — | Product name override |
| `--skip-image-upload` | flag | `False` | Extract images locally, skip Supabase upload |
| `--fail-fast` | flag | `False` | Abort on the first failed document |
| `--limit N` | integer | — | Process only the first N discovered documents |

---

## Data Models

All internal data is represented as Pydantic models (`src/rag_ingestion/models.py`):

**`SourceMetadata`** — document-level metadata attached to every chunk
- `vendor` — slugified vendor name (e.g. `raychem-catalogues`)
- `brand` — brand name (e.g. `Raychem`, `CharCoat`)
- `product` — product/category name
- `document_type` — `product_kb_pdf` or `product_kb_docx`

**`ExtractedDocument`** — full extraction output for one file
- `source_file`, `source_file_stem`, `source_path`, `file_hash`
- `metadata: SourceMetadata`
- `pages: list[ExtractedPage]`

**`ExtractedPage`** — one page (or the whole DOCX mapped to page 1)
- `page_number`, `text`, `tables: list[ExtractedTable]`, `images: list[ExtractedImage]`

**`ExtractedTable`**
- `page_number`, `table_number`, `rows: list[list[str]]`, `markdown`

**`ExtractedImage`**
- `page_number`, `image_number`, `xref` (PDF only), `width`, `height`
- `local_path` — path to saved PNG
- `storage_path` — path key inside Supabase bucket
- `image_url` — public Supabase URL (populated after upload)
- `caption` — regex-detected figure caption from page text
- `context_text` — first 2500 chars of surrounding page text

**`ChunkRecord`** — one vector store entry
- `id` — deterministic uuid5
- `text` — the text to embed and retrieve
- `metadata` — all payload fields
- `chunk_type` — `"text"`, `"table"`, or `"image_context"`

---

## Qdrant Point Structure

Each point upserted to Qdrant looks like this:

```json
{
  "id": "uuid5-deterministic-id",
  "vector": {
    "krishaa-dense-vector": [1536 floats]
  },
  "payload": {
    "text": "The extracted or context text...",
    "source_file": "1.1kV EPKT.pdf",
    "source_file_stem": "1.1kV EPKT",
    "source_path": "/abs/path/to/file.pdf",
    "file_hash": "sha256hex",
    "document_type": "product_kb_pdf",
    "vendor": "raychem-catalogues",
    "brand": "Krishaa",
    "product": "Support KB",
    "page_number": 3,
    "chunk_type": "text",
    "chunk_index": 12,
    "split_index": 0,
    "content_hash": "sha256hex",
    "image_url": "https://...",        // image_context chunks only
    "image_local_path": "...",
    "image_storage_path": "..."
  }
}
```

Payload indexes are automatically created for fast filtered retrieval on: `source_file`, `page_number`, `brand`, `product`, `vendor`, `chunk_type`.

---

## Incremental Ingestion

The pipeline uses SHA-256 file hashes to avoid reprocessing unchanged documents:

- On every successful run, the manifest at `data/ingestion_manifest.json` records the file hash, chunk IDs, and ingestion timestamp for each document.
- On the next run, if the hash matches, the document is skipped entirely.
- If a file is updated (hash changes) or `--force` is used:
  1. New chunks are extracted, embedded, and upserted.
  2. Stale chunk IDs from the previous manifest entry are deleted from Qdrant.
- If processing fails, the manifest records a `failed` status with the error message, preserving the previous chunk IDs if any existed.

Chunk IDs are derived deterministically from `file_hash + page_number + chunk_type + split_index` using `uuid5`, making reruns safe and idempotent.

Extraction JSON snapshots are written to `data/processed/{slug}.{hash12}.json` after each successful extraction. These are useful for offline debugging and reprocessing without re-reading the source files.

---

## Vendor Metadata Inference

When `--vendor` is not provided on the CLI, the pipeline infers the vendor from the document's path relative to `DOCUMENTS_DIR`:

```
knowledge/
├── Raychem_Catalogues/     → vendor: "raychem-catalogues"
│   └── product.pdf
├── Mennekes_Catalogues/    → vendor: "mennekes-catalogues"
│   └── product.pdf
└── product.pdf             → vendor: DEFAULT_VENDOR (from .env)
```

The first subdirectory name under `DOCUMENTS_DIR` is slugified and used as the vendor. Files placed directly in `DOCUMENTS_DIR` (no subdirectory) fall back to `DEFAULT_VENDOR`.

---

## DOCX Handling

DOCX files are processed using the same internal model as PDFs:

- Paragraphs are joined and become `text` chunks.
- Word tables become Markdown `table` chunks.
- Embedded images are extracted from `part.related_parts`, deduplicated by SHA-256, converted to PNG with Pillow, uploaded to Supabase when enabled, and stored as `image_context` chunks.
- `document_type` is set to `product_kb_docx`.
- Because DOCX files have no stable page numbers without a layout engine, all DOCX content is mapped to `page_number=1`.

---

## RAG Query Guide

At query time, the retrieval layer should:

1. Embed the user question with the same model (`text-embedding-3-small`, 1536 dims).
2. Query Qdrant using the configured named vector (`QDRANT_VECTOR_NAME`).
3. Apply payload filters such as `vendor`, `brand`, `product`, `source_file`, or `chunk_type` to narrow results.
4. Pass the retrieved `text` payload values to the answering LLM as context.
5. For `image_context` chunks, include `image_url` in the response when the chunk is relevant enough.

Example filter patterns:

```python
# Filter by vendor and chunk type
from qdrant_client import models

filter = models.Filter(
    must=[
        models.FieldCondition(key="vendor", match=models.MatchValue(value="raychem-catalogues")),
        models.FieldCondition(key="chunk_type", match=models.MatchAny(any=["text", "table"])),
    ]
)
```

A quick manual test against the live Qdrant collection is available in `test/test.py`.

---

## Testing

A manual end-to-end query test is included:

```bash
# Ensure .env is configured, then:
python test/test.py
```

This embeds a hardcoded query, searches Qdrant for the top 3 results, and prints the score, vendor, source file, page number, chunk type, image URL, and a text preview for each match.

There is no automated test suite yet. Unit tests can be added under `test/` using any standard Python test runner (pytest is recommended).

---

## Tech Stack

| Category | Library | Version |
|---|---|---|
| CLI | [typer](https://typer.tiangolo.com) | >=0.12.0 |
| Configuration | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | >=2.4.0 |
| PDF text/tables | [pdfplumber](https://github.com/jsvine/pdfplumber) | >=0.11.0 |
| PDF images | [PyMuPDF](https://pymupdf.readthedocs.io) (fitz) | >=1.24.0 |
| DOCX | [python-docx](https://python-docx.readthedocs.io) | >=1.1.2 |
| Image processing | [Pillow](https://pillow.readthedocs.io) | >=10.0.0 |
| Embeddings | [langchain-openai](https://python.langchain.com/docs/integrations/text_embedding/openai/) | >=0.2.0 |
| Text splitting | [langchain-text-splitters](https://python.langchain.com/docs/how_to/recursive_text_splitter/) | >=0.3.0 |
| Token counting | [tiktoken](https://github.com/openai/tiktoken) | >=0.7.0 |
| Vector DB | [qdrant-client](https://python-client.qdrant.tech) | >=1.11.0 |
| Image storage | [supabase-py](https://supabase.com/docs/reference/python/introduction) | >=2.7.0 |
| Retry logic | [tenacity](https://tenacity.readthedocs.io) | >=8.5.0 |
| Console output | [rich](https://rich.readthedocs.io) | >=13.7.0 |
| Python | — | >=3.11 |
