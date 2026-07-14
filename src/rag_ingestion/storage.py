from __future__ import annotations

import logging
from pathlib import Path

from supabase import Client, create_client

from rag_ingestion.config import Settings
from rag_ingestion.models import ExtractedDocument

logger = logging.getLogger(__name__)


class SupabaseImageStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for image upload")

        self.bucket_name = settings.supabase_storage_bucket
        self.client: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        self.bucket = self.client.storage.from_(self.bucket_name)

    def upload_document_images(self, document: ExtractedDocument) -> ExtractedDocument:
        for page in document.pages:
            for image in page.images:
                image.image_url = self.upload_image(Path(image.local_path), image.storage_path)
        return document

    def upload_image(self, local_path: Path, storage_path: str) -> str:
        logger.debug("Uploading image to Supabase: %s", storage_path)
        with local_path.open("rb") as file:
            self.bucket.upload(
                path=storage_path,
                file=file,
                file_options={
                    "content-type": "image/png",
                    "cache-control": "31536000",
                    "upsert": "true",
                },
            )

        public_url = self.bucket.get_public_url(storage_path)
        if isinstance(public_url, dict):
            return str(public_url.get("publicUrl") or public_url.get("public_url") or "")
        return str(public_url)
