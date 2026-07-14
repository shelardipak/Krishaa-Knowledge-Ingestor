from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChunkType = Literal["text", "table", "image_context"]


class SourceMetadata(BaseModel):
    vendor: str
    brand: str | None = None
    product: str | None = None
    document_type: str = "product_kb_pdf"


class ExtractedTable(BaseModel):
    page_number: int
    table_number: int
    rows: list[list[str]]
    markdown: str


class ExtractedImage(BaseModel):
    page_number: int
    image_number: int
    xref: int | None = None
    width: int | None = None
    height: int | None = None
    local_path: str
    storage_path: str
    image_url: str | None = None
    caption: str | None = None
    context_text: str | None = None


class ExtractedPage(BaseModel):
    page_number: int
    text: str
    tables: list[ExtractedTable] = Field(default_factory=list)
    images: list[ExtractedImage] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    source_file: str
    source_file_stem: str
    source_path: str
    file_hash: str
    metadata: SourceMetadata
    pages: list[ExtractedPage]
    extracted_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ChunkRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    metadata: dict[str, Any]
    chunk_type: ChunkType
