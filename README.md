# Product KB RAG Ingestion

This repository provides a production-oriented Python ingestion pipeline for loading product-support knowledge from PDF and DOCX files into Qdrant Cloud for retrieval-augmented generation (RAG). It extracts text, tables, and images, uploads images to Supabase Storage when enabled, generates embeddings with OpenAI, and upserts vectors into Qdrant with deterministic IDs.

## What the pipeline does

- Discovers supported files from a configured input directory
- Extracts text and tables from PDFs and DOCX files
- Extracts embedded images from PDFs and DOCX documents
- Uploads extracted images to Supabase Storage (optional)
- Generates embeddings with OpenAI and writes them to Qdrant
- Tracks processed files in a manifest so unchanged documents are skipped on later runs

## Repository structure

```text
.
├── data/                         # Runtime artifacts and extracted content
│   ├── extracted_images/        # Temporary local image extracts
│   ├── processed/               # Normalized extraction JSON output
│   └── ingestion_manifest.json  # Incremental ingestion state
├── knowledge/                   # Default source documents directory
├── src/rag_ingestion/           # Core package implementation
│   ├── cli.py                   # Typer CLI entrypoint
│   ├── config.py                # Environment-driven settings
│   ├── discovery.py             # File discovery logic
│   ├── extractors/              # PDF and DOCX extractors
│   ├── pipeline.py              # End-to-end orchestration
│   └── ...                      # Chunking, embeddings, storage, and vector-store modules
├── test/                        # Basic validation scripts
├── .env.example                 # Sample environment configuration
└── pyproject.toml               # Package metadata and dependencies
```

## Prerequisites

- Python 3.11 or newer
- Access to:
  - OpenAI API
  - Qdrant Cloud or a self-hosted Qdrant instance
  - Supabase Storage (optional, required if image upload is enabled)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` with your service credentials and preferred settings before running the ingestion pipeline.

## Configuration

The project reads settings from `.env` using the `pydantic-settings` package. The most important variables are:

- `OPENAI_API_KEY`: Your OpenAI API key
- `EMBEDDING_MODEL`: Embedding model to use (default: `text-embedding-3-small`)
- `EMBEDDING_DIMENSIONS`: Embedding dimensionality (default: `1536`)
- `QDRANT_URL`: Qdrant endpoint URL
- `QDRANT_API_KEY`: Qdrant API key, if required
- `QDRANT_COLLECTION`: The target collection name
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`: Supabase credentials for image uploads
- `DOCUMENTS_DIR`: Source documents directory (default: `knowledge`)
- `PROCESSED_DIR`, `EXTRACTED_IMAGES_DIR`, and `INGESTION_MANIFEST_PATH`: Output and state locations

The example file already includes sensible defaults for local paths and chunking behavior. If your Qdrant collection uses named vectors, set `QDRANT_VECTOR_NAME` accordingly.

## Running ingestion

Place your PDFs and DOCX files under the configured documents directory, then run:

```bash
rag-ingest run --vendor krishaa --brand "Krishaa" --product "Support KB"
```

Useful CLI options include:

```bash
rag-ingest run --force
rag-ingest run --limit 1 --fail-fast
rag-ingest run --skip-image-upload
```

## Output and storage model

Each Qdrant point contains:

- An embedding generated from normalized extracted text
- Payload text for retrieval context
- Metadata such as `source_file`, `source_file_stem`, `source_path`, and `file_hash`
- `page_number`, `document_type`, `vendor`, `brand`, and `product`
- `chunk_type`: `text`, `table`, or `image_context`
- Image metadata for image-context chunks when images are uploaded

Raw image bytes are not stored in Qdrant and are not sent to the embedding model.

## Incremental ingestion

The pipeline computes a SHA-256 hash per document and stores successful runs in `data/ingestion_manifest.json`.

- Unchanged documents are skipped by default
- Deterministic chunk IDs allow safe reruns and upserts
- If a file changes, or if `--force` is used, new chunks are upserted and stale point IDs from the previous manifest entry are removed after successful processing
- Normalized extraction output is written to `data/processed/*.json` for debugging and reprocessing

## DOCX handling notes

DOCX files are processed using the same internal model as PDFs:

- Paragraphs become `text` chunks
- Word tables become Markdown `table` chunks
- Embedded images are converted to PNG, uploaded to Supabase when enabled, and represented as `image_context` chunks
- `document_type` is stored as `product_kb_docx`

DOCX files do not contain stable page numbers until rendered by Word or another layout engine, so DOCX chunks use `page_number=1`.

## Notes for downstream RAG usage

At query time, the retrieval layer should:

1. Embed the user question with the same OpenAI embedding model
2. Search Qdrant with filters such as `vendor`, `brand`, `product`, `source_file`, or `chunk_type`
3. Pass the retrieved payload text to the answering model as context
4. Include `image_url` only when an `image_context` chunk is relevant enough for the final answer

For product support use cases, a useful first filter is `chunk_type in ["text", "table", "image_context"]`, combined with product or vendor metadata when known.
