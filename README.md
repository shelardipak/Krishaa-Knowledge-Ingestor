# Product KB RAG Ingestion

Production-ready Python ingestion pipeline for loading product-support PDF and DOCX knowledge bases into Qdrant Cloud. It extracts text, tables, and images, uploads extracted images to Supabase Storage, embeds normalized text chunks with OpenAI `text-embedding-3-small`, and upserts vectors into Qdrant with stable point IDs.

## Folder Structure

```text
.
├── knowledge/documents/          # Put source PDFs and DOCX files here
├── data/
│   ├── extracted_images/         # Temporary local image extracts
│   ├── processed/                # Raw normalized extraction JSON
│   └── ingestion_manifest.json   # Incremental ingestion state
├── src/rag_ingestion/
│   ├── cli.py                    # Typer CLI
│   ├── config.py                 # Environment-driven settings
│   ├── discovery.py              # PDF/DOCX discovery
│   ├── extractors/docx.py        # python-docx extraction
│   ├── extractors/pdf.py         # pdfplumber + PyMuPDF extraction
│   ├── chunking.py               # LangChain text splitting
│   ├── embeddings.py             # OpenAI embedding generation
│   ├── storage.py                # Supabase image uploads
│   ├── vector_store.py           # Qdrant collection/index/upsert
│   ├── manifest.py               # Incremental ingestion manifest
│   └── pipeline.py               # End-to-end orchestration
├── .env.example
└── pyproject.toml
```

## Dependencies

Core packages are declared in `pyproject.toml`:

- LangChain, `langchain-openai`, and LangChain text splitters
- `pdfplumber` for page text and table extraction
- `PyMuPDF` / `fitz` for image extraction
- `python-docx` for DOCX paragraph, table, and embedded image extraction
- `Pillow` for converting DOCX images to PNG
- OpenAI embeddings via `text-embedding-3-small`
- `qdrant-client` for Qdrant Cloud
- `supabase` for Storage uploads
- `pydantic-settings`, `typer`, `rich`, `tenacity`, and `tiktoken`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` with your OpenAI, Qdrant Cloud, and Supabase values. The Qdrant collection uses vector size `1536`, matching the default dimensionality of `text-embedding-3-small`. `QDRANT_CHECK_COMPATIBILITY=false` avoids a non-critical Qdrant Cloud server-version warning during client startup. If your collection uses named vectors, set `QDRANT_VECTOR_NAME` to the existing vector name.

Create a public Supabase Storage bucket named `product-images`. Images are uploaded with this path format:

```text
{vendor}/{source_file_stem}/page_{page_number}_img_{image_number}.png
```

## Run Ingestion

Put PDFs and DOCX files inside `knowledge/documents/`, then run:

```bash
rag-ingest run --vendor krishaa --brand "Krishaa" --product "Support KB"
```

Useful options:

```bash
rag-ingest run --force
rag-ingest run --limit 1 --fail-fast
rag-ingest run --skip-image-upload
```

## What Gets Stored

Each Qdrant point contains:

- Vector embedding generated from extracted and normalized text only
- Payload `text` for retrieval context
- `source_file`, `source_file_stem`, `source_path`, and `file_hash`
- `page_number` and `document_type`
- `vendor`, `brand`, and `product`
- `chunk_type`: `text`, `table`, or `image_context`
- Image metadata for image context chunks: `image_local_path`, `image_storage_path`, and `image_url`

Raw image bytes are never stored in Qdrant and are never sent to `text-embedding-3-small`.

## Incremental Ingestion

The pipeline computes a SHA-256 hash per document and stores successful runs in `data/ingestion_manifest.json`.

- Unchanged documents are skipped by default.
- Chunk IDs are deterministic UUIDs, so reruns upsert safely.
- If a file changes or `--force` is used, new chunks are upserted first and stale point IDs from the previous manifest entry are deleted after a successful upsert.
- Normalized extraction output is written to `data/processed/*.json` for debugging and reprocessing.

## DOCX Notes

DOCX files are extracted into the same internal model as PDFs:

- paragraphs become `text` chunks
- Word tables become Markdown `table` chunks
- embedded images are converted to PNG, uploaded to Supabase, and represented as `image_context` chunks
- `document_type` is stored as `product_kb_docx`

DOCX files do not contain stable page numbers until rendered by Word or another layout engine, so DOCX chunks use `page_number=1`.

## Retrieval Notes For Chatbot Backend

At query time:

1. Embed the user question with the same OpenAI embedding model.
2. Search Qdrant with optional filters such as `vendor`, `brand`, `product`, `source_file`, or `chunk_type`.
3. Send retrieved payload `text` to the answer-generation model as context.
4. Return `image_url` only when a retrieved `image_context` chunk is relevant enough for the final answer.
5. Let the frontend render returned images directly from the public Supabase URL.

For product support, a useful first filter is `chunk_type in ["text", "table", "image_context"]` plus a product/vendor filter when the active customer or product is known.
