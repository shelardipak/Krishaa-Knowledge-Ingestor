from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(1536, alias="EMBEDDING_DIMENSIONS")

    qdrant_url: str = Field(..., alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field("product_knowledge", alias="QDRANT_COLLECTION")
    qdrant_check_compatibility: bool = Field(False, alias="QDRANT_CHECK_COMPATIBILITY")
    qdrant_vector_name: str | None = Field(None, alias="QDRANT_VECTOR_NAME")

    supabase_url: str | None = Field(None, alias="SUPABASE_URL")
    supabase_service_role_key: str | None = Field(None, alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_storage_bucket: str = Field("product-images", alias="SUPABASE_STORAGE_BUCKET")

    documents_dir: Path = Field(Path("knowledge/documents"), alias="DOCUMENTS_DIR")
    extracted_images_dir: Path = Field(Path("data/extracted_images"), alias="EXTRACTED_IMAGES_DIR")
    processed_dir: Path = Field(Path("data/processed"), alias="PROCESSED_DIR")
    ingestion_manifest_path: Path = Field(
        Path("data/ingestion_manifest.json"), alias="INGESTION_MANIFEST_PATH"
    )

    chunk_size_tokens: int = Field(800, alias="CHUNK_SIZE_TOKENS")
    chunk_overlap_tokens: int = Field(120, alias="CHUNK_OVERLAP_TOKENS")
    embedding_batch_size: int = Field(64, alias="EMBEDDING_BATCH_SIZE")
    upsert_batch_size: int = Field(64, alias="UPSERT_BATCH_SIZE")

    default_vendor: str = Field("unknown_vendor", alias="DEFAULT_VENDOR")
    default_brand: str | None = Field(None, alias="DEFAULT_BRAND")
    default_product: str | None = Field(None, alias="DEFAULT_PRODUCT")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    min_image_width: int = Field(1, alias="MIN_IMAGE_WIDTH")
    min_image_height: int = Field(1, alias="MIN_IMAGE_HEIGHT")

    def ensure_local_dirs(self) -> None:
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_images_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.ingestion_manifest_path.parent.mkdir(parents=True, exist_ok=True)
