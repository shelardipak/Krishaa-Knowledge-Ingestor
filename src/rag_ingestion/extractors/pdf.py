from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz
import pdfplumber

from rag_ingestion.config import Settings
from rag_ingestion.models import (
    ExtractedDocument,
    ExtractedImage,
    ExtractedPage,
    ExtractedTable,
    SourceMetadata,
)
from rag_ingestion.utils import compact_whitespace, slugify

logger = logging.getLogger(__name__)


class PdfExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, pdf_path: Path, file_hash: str, metadata: SourceMetadata) -> ExtractedDocument:
        logger.info("Extracting PDF: %s", pdf_path.name)
        pages: list[ExtractedPage] = []

        with pdfplumber.open(pdf_path) as plumber_pdf, fitz.open(pdf_path) as fitz_pdf:
            for page_index, plumber_page in enumerate(plumber_pdf.pages):
                page_number = page_index + 1
                page_text = plumber_page.extract_text() or ""
                tables = self._extract_tables(plumber_page, page_number)
                images = self._extract_images(
                    fitz_pdf=fitz_pdf,
                    source_pdf=pdf_path,
                    page_index=page_index,
                    page_number=page_number,
                    page_text=page_text,
                    metadata=metadata,
                )
                pages.append(
                    ExtractedPage(
                        page_number=page_number,
                        text=page_text.strip(),
                        tables=tables,
                        images=images,
                    )
                )

        return ExtractedDocument(
            source_file=pdf_path.name,
            source_file_stem=pdf_path.stem,
            source_path=str(pdf_path),
            file_hash=file_hash,
            metadata=metadata,
            pages=pages,
        )

    def _extract_tables(self, plumber_page: pdfplumber.page.Page, page_number: int) -> list[ExtractedTable]:
        extracted_tables: list[ExtractedTable] = []

        try:
            raw_tables = plumber_page.extract_tables() or []
        except Exception:
            logger.exception("Failed to extract tables from page %s", page_number)
            return extracted_tables

        for table_index, raw_rows in enumerate(raw_tables, start=1):
            rows = self._normalize_table_rows(raw_rows)
            if not rows:
                continue
            markdown = self._table_to_markdown(rows)
            extracted_tables.append(
                ExtractedTable(
                    page_number=page_number,
                    table_number=table_index,
                    rows=rows,
                    markdown=markdown,
                )
            )

        return extracted_tables

    def _extract_images(
        self,
        *,
        fitz_pdf: fitz.Document,
        source_pdf: Path,
        page_index: int,
        page_number: int,
        page_text: str,
        metadata: SourceMetadata,
    ) -> list[ExtractedImage]:
        page = fitz_pdf[page_index]
        extracted_images: list[ExtractedImage] = []

        try:
            image_refs = page.get_images(full=True)
        except Exception:
            logger.exception("Failed to inspect images on page %s", page_number)
            return extracted_images

        for image_index, image_ref in enumerate(image_refs, start=1):
            xref = image_ref[0]
            try:
                pix = fitz.Pixmap(fitz_pdf, xref)
                if pix.width < self.settings.min_image_width or pix.height < self.settings.min_image_height:
                    pix = None
                    continue

                if pix.alpha or pix.n >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                local_path = self._local_image_path(source_pdf, page_number, image_index)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                pix.save(local_path)

                extracted_images.append(
                    ExtractedImage(
                        page_number=page_number,
                        image_number=image_index,
                        xref=xref,
                        width=pix.width,
                        height=pix.height,
                        local_path=str(local_path),
                        storage_path=self._storage_image_path(
                            metadata.vendor, source_pdf.stem, page_number, image_index
                        ),
                        caption=self._find_caption(page_text, image_index),
                        context_text=self._image_context_text(page_text),
                    )
                )
                pix = None
            except Exception:
                logger.exception(
                    "Failed to extract image %s on page %s of %s",
                    image_index,
                    page_number,
                    source_pdf.name,
                )

        return extracted_images

    def _local_image_path(self, source_pdf: Path, page_number: int, image_number: int) -> Path:
        source_stem = slugify(source_pdf.stem, fallback="document")
        return (
            self.settings.extracted_images_dir
            / source_stem
            / f"page_{page_number}_img_{image_number}.png"
        )

    def _storage_image_path(
        self, vendor: str, source_file_stem: str, page_number: int, image_number: int
    ) -> str:
        return (
            f"{slugify(vendor, fallback='unknown_vendor')}/"
            f"{slugify(source_file_stem, fallback='document')}/"
            f"page_{page_number}_img_{image_number}.png"
        )

    def _normalize_table_rows(self, rows: list[list[str | None]]) -> list[list[str]]:
        normalized: list[list[str]] = []
        for row in rows:
            normalized_row = [compact_whitespace(cell) for cell in row]
            if any(normalized_row):
                normalized.append(normalized_row)
        return normalized

    def _table_to_markdown(self, rows: list[list[str]]) -> str:
        max_columns = max(len(row) for row in rows)
        padded_rows = [row + [""] * (max_columns - len(row)) for row in rows]

        header = [
            self._escape_markdown_cell(cell) if cell else f"Column {index + 1}"
            for index, cell in enumerate(padded_rows[0])
        ]
        body = padded_rows[1:] or [[""] * max_columns]

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * max_columns) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(self._escape_markdown_cell(cell) for cell in row) + " |")
        return "\n".join(lines)

    def _escape_markdown_cell(self, value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    def _find_caption(self, page_text: str, image_number: int) -> str | None:
        caption_pattern = re.compile(
            r"(?im)^\s*((figure|fig\.|image|diagram)\s*"
            + re.escape(str(image_number))
            + r"[\w.\-:)]*\s+.+)$"
        )
        match = caption_pattern.search(page_text)
        if match:
            return compact_whitespace(match.group(1))

        generic_pattern = re.compile(r"(?im)^\s*((figure|fig\.|image|diagram)[\w\s.\-:)]{3,160})$")
        match = generic_pattern.search(page_text)
        if match:
            return compact_whitespace(match.group(1))

        return None

    def _image_context_text(self, page_text: str, max_chars: int = 2500) -> str:
        text = compact_whitespace(page_text)
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0]
