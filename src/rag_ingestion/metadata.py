from pathlib import Path

from rag_ingestion.config import Settings
from rag_ingestion.models import SourceMetadata
from rag_ingestion.utils import slugify


def infer_source_metadata(
    source_path: Path,
    settings: Settings,
    vendor: str | None = None,
    brand: str | None = None,
    product: str | None = None,
    document_type: str = "product_kb_pdf",
) -> SourceMetadata:
    inferred_vendor = vendor or _vendor_from_path(source_path, settings.documents_dir) or settings.default_vendor
    return SourceMetadata(
        vendor=slugify(inferred_vendor, fallback="unknown_vendor"),
        brand=brand or settings.default_brand or None,
        product=product or settings.default_product or None,
        document_type=document_type,
    )


def _vendor_from_path(pdf_path: Path, documents_dir: Path) -> str | None:
    try:
        relative = pdf_path.relative_to(documents_dir)
    except ValueError:
        return None

    if len(relative.parts) > 1:
        return relative.parts[0]
    return None
