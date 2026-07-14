import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx"}


def discover_documents(documents_dir: Path) -> list[Path]:
    if not documents_dir.exists():
        logger.warning("Documents directory does not exist: %s", documents_dir)
        return []

    documents = sorted(
        path
        for path in documents_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
        and not path.name.startswith("~$")
    )
    logger.info("Discovered %s document file(s) in %s", len(documents), documents_dir)
    return documents


def discover_pdfs(documents_dir: Path) -> list[Path]:
    return [path for path in discover_documents(documents_dir) if path.suffix.lower() == ".pdf"]
