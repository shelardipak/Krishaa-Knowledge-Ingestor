from __future__ import annotations

import json
import logging
from pathlib import Path

from rag_ingestion.chunking import DocumentChunker
from rag_ingestion.config import Settings
from rag_ingestion.discovery import discover_documents
from rag_ingestion.embeddings import EmbeddingGenerator
from rag_ingestion.extractors import DocxExtractor, PdfExtractor
from rag_ingestion.manifest import IngestionManifest
from rag_ingestion.metadata import infer_source_metadata
from rag_ingestion.storage import SupabaseImageStorage
from rag_ingestion.utils import sha256_file, slugify
from rag_ingestion.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pdf_extractor = PdfExtractor(settings)
        self.docx_extractor = DocxExtractor(settings)
        self.chunker = DocumentChunker(settings)
        self.embedder = EmbeddingGenerator(settings)
        self.vector_store = QdrantVectorStore(settings)

    def run(
        self,
        *,
        force: bool = False,
        vendor: str | None = None,
        brand: str | None = None,
        product: str | None = None,
        upload_images: bool = True,
        fail_fast: bool = False,
        limit: int | None = None,
    ) -> None:
        self.settings.ensure_local_dirs()
        self.vector_store.ensure_collection()

        manifest = IngestionManifest.load(self.settings.ingestion_manifest_path)
        documents = discover_documents(self.settings.documents_dir)
        if limit:
            documents = documents[:limit]
        if not documents:
            logger.info("No PDF or DOCX files found. Add files to %s", self.settings.documents_dir)
            return

        image_storage = SupabaseImageStorage(self.settings) if upload_images else None

        for document_path in documents:
            try:
                self._process_document(
                    document_path=document_path,
                    manifest=manifest,
                    force=force,
                    vendor=vendor,
                    brand=brand,
                    product=product,
                    image_storage=image_storage,
                )
                manifest.save()
            except Exception as exc:
                relative_path = self._relative_document_path(document_path)
                manifest.mark_failed(
                    relative_path=relative_path,
                    file_hash=sha256_file(document_path),
                    error=str(exc),
                )
                manifest.save()
                logger.exception("Failed to ingest %s", document_path.name)
                if fail_fast:
                    raise

    def _process_document(
        self,
        *,
        document_path: Path,
        manifest: IngestionManifest,
        force: bool,
        vendor: str | None,
        brand: str | None,
        product: str | None,
        image_storage: SupabaseImageStorage | None,
    ) -> None:
        relative_path = self._relative_document_path(document_path)
        file_hash = sha256_file(document_path)
        previous_entry = manifest.get_file(relative_path)

        if manifest.is_current(relative_path, file_hash) and not force:
            logger.info("Skipping unchanged document: %s", relative_path)
            return

        document_type = self._document_type(document_path)
        source_metadata = infer_source_metadata(
            source_path=document_path,
            settings=self.settings,
            vendor=vendor,
            brand=brand,
            product=product,
            document_type=document_type,
        )
        extracted_document = self._extract_document(document_path, file_hash, source_metadata)

        if image_storage:
            extracted_document = image_storage.upload_document_images(extracted_document)

        extraction_json_path = self._write_extraction_json(extracted_document)
        chunks = self.chunker.chunk(extracted_document)
        if not chunks:
            logger.warning("No chunks produced for %s", relative_path)
            return

        embeddings = self.embedder.embed_chunks(chunks)
        self.vector_store.upsert_chunks(chunks, embeddings)

        chunk_ids = [chunk.id for chunk in chunks]
        stale_chunk_ids = self._stale_chunk_ids(previous_entry, chunk_ids)
        if stale_chunk_ids:
            self.vector_store.delete_points(stale_chunk_ids)

        manifest.mark_success(
            relative_path=relative_path,
            file_hash=file_hash,
            source_file=document_path.name,
            chunk_ids=chunk_ids,
            extraction_json_path=str(extraction_json_path),
        )
        logger.info("Ingested %s with %s chunk(s)", relative_path, len(chunks))

    def _write_extraction_json(self, document) -> Path:
        source_stem = slugify(document.source_file_stem, fallback="document")
        output_path = self.settings.processed_dir / f"{source_stem}.{document.file_hash[:12]}.json"
        with output_path.open("w", encoding="utf-8") as file:
            json.dump(document.model_dump(), file, indent=2, ensure_ascii=False)
            file.write("\n")
        return output_path

    def _extract_document(self, document_path: Path, file_hash: str, source_metadata):
        suffix = document_path.suffix.lower()
        if suffix == ".pdf":
            return self.pdf_extractor.extract(document_path, file_hash, source_metadata)
        if suffix == ".docx":
            return self.docx_extractor.extract(document_path, file_hash, source_metadata)
        raise ValueError(f"Unsupported document type: {document_path.suffix}")

    def _document_type(self, document_path: Path) -> str:
        suffix = document_path.suffix.lower().lstrip(".")
        return f"product_kb_{suffix}"

    def _relative_document_path(self, document_path: Path) -> str:
        try:
            return str(document_path.relative_to(self.settings.documents_dir))
        except ValueError:
            return str(document_path)

    def _stale_chunk_ids(self, previous_entry: dict | None, new_chunk_ids: list[str]) -> list[str]:
        if not previous_entry or not previous_entry.get("chunk_ids"):
            return []
        return sorted(set(previous_entry["chunk_ids"]) - set(new_chunk_ids))
