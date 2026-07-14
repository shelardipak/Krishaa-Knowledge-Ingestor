from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_ingestion.config import Settings
from rag_ingestion.models import ChunkRecord, ChunkType, ExtractedDocument, ExtractedImage, ExtractedTable
from rag_ingestion.utils import compact_whitespace, sha256_text


class DocumentChunker:
    def __init__(self, settings: Settings) -> None:
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",
            chunk_size=settings.chunk_size_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
        )

    def chunk(self, document: ExtractedDocument) -> list[ChunkRecord]:
        source_documents = self._to_langchain_documents(document)
        split_documents = self.splitter.split_documents(source_documents)
        counters: dict[tuple[Any, ...], int] = defaultdict(int)
        chunks: list[ChunkRecord] = []

        for global_index, split_doc in enumerate(split_documents):
            metadata = dict(split_doc.metadata)
            chunk_type: ChunkType = metadata["chunk_type"]
            key = (
                metadata["file_hash"],
                metadata["page_number"],
                chunk_type,
                metadata.get("table_number"),
                metadata.get("image_number"),
            )
            split_index = counters[key]
            counters[key] += 1

            text = split_doc.page_content.strip()
            metadata.update(
                {
                    "chunk_index": global_index,
                    "split_index": split_index,
                    "content_hash": sha256_text(text),
                }
            )
            chunks.append(
                ChunkRecord(
                    id=self._stable_chunk_id(metadata),
                    text=text,
                    metadata=metadata,
                    chunk_type=chunk_type,
                )
            )

        return chunks

    def _to_langchain_documents(self, document: ExtractedDocument) -> list[Document]:
        langchain_docs: list[Document] = []
        base_metadata = self._base_metadata(document)

        for page in document.pages:
            page_metadata = {**base_metadata, "page_number": page.page_number}
            page_text = compact_whitespace(page.text)
            if page_text:
                langchain_docs.append(
                    Document(
                        page_content=page_text,
                        metadata={**page_metadata, "chunk_type": "text"},
                    )
                )

            for table in page.tables:
                langchain_docs.append(
                    Document(
                        page_content=self._table_content(table),
                        metadata={
                            **page_metadata,
                            "chunk_type": "table",
                            "table_number": table.table_number,
                        },
                    )
                )

            for image in page.images:
                image_content = self._image_content(image)
                if image_content:
                    langchain_docs.append(
                        Document(
                            page_content=image_content,
                            metadata={
                                **page_metadata,
                                "chunk_type": "image_context",
                                "image_number": image.image_number,
                                "image_local_path": image.local_path,
                                "image_storage_path": image.storage_path,
                                "image_url": image.image_url,
                            },
                        )
                    )

        return langchain_docs

    def _base_metadata(self, document: ExtractedDocument) -> dict[str, Any]:
        return {
            "source_file": document.source_file,
            "source_file_stem": document.source_file_stem,
            "source_path": document.source_path,
            "file_hash": document.file_hash,
            "document_type": document.metadata.document_type,
            "vendor": document.metadata.vendor,
            "brand": document.metadata.brand,
            "product": document.metadata.product,
        }

    def _table_content(self, table: ExtractedTable) -> str:
        return f"Table {table.table_number} on page {table.page_number}\n\n{table.markdown}"

    def _image_content(self, image: ExtractedImage) -> str:
        parts = [f"Image {image.image_number} on page {image.page_number}"]
        if image.caption:
            parts.append(f"Caption: {image.caption}")
        if image.context_text:
            parts.append(f"Nearby page text: {image.context_text}")
        return "\n\n".join(parts).strip()

    def _stable_chunk_id(self, metadata: dict[str, Any]) -> str:
        stable_key = "|".join(
            str(metadata.get(key, ""))
            for key in (
                "file_hash",
                "page_number",
                "chunk_type",
                "table_number",
                "image_number",
                "split_index",
            )
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"krishaa-rag:{stable_key}"))
