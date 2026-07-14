from __future__ import annotations

import logging

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_ingestion.config import Settings
from rag_ingestion.models import ChunkRecord
from rag_ingestion.utils import batched

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    def __init__(self, settings: Settings) -> None:
        self.collection_name = settings.qdrant_collection
        self.vector_size = settings.embedding_dimensions
        self.vector_name = settings.qdrant_vector_name
        self.upsert_batch_size = settings.upsert_batch_size
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            check_compatibility=settings.qdrant_check_compatibility,
        )

    def ensure_collection(self) -> None:
        if not self._collection_exists():
            logger.info("Creating Qdrant collection %s", self.collection_name)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self._vectors_config(),
            )
        else:
            logger.info("Qdrant collection already exists: %s", self.collection_name)
            self._validate_existing_collection()

        self._ensure_payload_indexes()

    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunks and embeddings length mismatch")

        points = [
            models.PointStruct(
                id=chunk.id,
                vector=self._point_vector(embedding),
                payload=self._payload_for_chunk(chunk),
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        for batch_number, batch in enumerate(batched(points, self.upsert_batch_size), start=1):
            logger.info("Upserting Qdrant batch %s (%s point(s))", batch_number, len(batch))
            self.client.upsert(
                collection_name=self.collection_name,
                points=list(batch),
                wait=True,
            )

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return

        for batch in batched(point_ids, self.upsert_batch_size):
            logger.info("Deleting %s stale Qdrant point(s)", len(batch))
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=list(batch)),
                wait=True,
            )

    def _collection_exists(self) -> bool:
        try:
            if hasattr(self.client, "collection_exists"):
                return bool(self.client.collection_exists(collection_name=self.collection_name))

            self.client.get_collection(collection_name=self.collection_name)
            return True
        except UnexpectedResponse as exc:
            if self._unexpected_status_code(exc) == 404:
                return False
            self._raise_qdrant_access_error(exc)
        except Exception as exc:
            message = str(exc).lower()
            if "not found" in message or "404" in message:
                return False
            raise

    def _ensure_payload_indexes(self) -> None:
        indexes = {
            "source_file": models.PayloadSchemaType.KEYWORD,
            "page_number": models.PayloadSchemaType.INTEGER,
            "brand": models.PayloadSchemaType.KEYWORD,
            "product": models.PayloadSchemaType.KEYWORD,
            "vendor": models.PayloadSchemaType.KEYWORD,
            "chunk_type": models.PayloadSchemaType.KEYWORD,
        }

        for field_name, schema in indexes.items():
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=schema,
                    wait=True,
                )
            except Exception as exc:
                message = str(exc).lower()
                if "already exists" in message or "exists" in message:
                    logger.debug("Payload index already exists: %s", field_name)
                    continue
                logger.warning("Could not create payload index %s: %s", field_name, exc)

    def _payload_for_chunk(self, chunk: ChunkRecord) -> dict:
        payload = {"text": chunk.text, **chunk.metadata}
        return {key: value for key, value in payload.items() if value is not None}

    def _validate_existing_collection(self) -> None:
        try:
            collection = self.client.get_collection(collection_name=self.collection_name)
            vectors_config = collection.config.params.vectors
            vector_names = self._vector_names_from_config(vectors_config)
            self._resolve_vector_name(vector_names)
            existing_size = self._vector_size_from_config(vectors_config)
        except Exception as exc:
            logger.warning("Could not validate existing Qdrant collection schema: %s", exc)
            return

        if existing_size and existing_size != self.vector_size:
            raise ValueError(
                f"Qdrant collection {self.collection_name!r} has vector size {existing_size}, "
                f"but this pipeline is configured for {self.vector_size}."
            )

    def _vectors_config(self):
        vector_params = models.VectorParams(
            size=self.vector_size,
            distance=models.Distance.COSINE,
        )
        if self.vector_name:
            return {self.vector_name: vector_params}
        return vector_params

    def _point_vector(self, embedding: list[float]):
        if self.vector_name:
            return {self.vector_name: embedding}
        return embedding

    def _resolve_vector_name(self, vector_names: list[str]) -> None:
        if self.vector_name:
            if vector_names and self.vector_name not in vector_names:
                raise ValueError(
                    f"QDRANT_VECTOR_NAME={self.vector_name!r} does not exist in "
                    f"collection {self.collection_name!r}. Existing vector names: {vector_names}"
                )
            return

        if len(vector_names) == 1:
            self.vector_name = vector_names[0]
            logger.info("Using Qdrant named vector: %s", self.vector_name)
            return

        if len(vector_names) > 1:
            raise ValueError(
                f"Collection {self.collection_name!r} has multiple named vectors: {vector_names}. "
                "Set QDRANT_VECTOR_NAME in .env."
            )

    def _vector_names_from_config(self, vectors_config) -> list[str]:
        if isinstance(vectors_config, dict):
            return list(vectors_config.keys())
        return []

    def _vector_size_from_config(self, vectors_config) -> int | None:
        if self.vector_name and isinstance(vectors_config, dict):
            return self._vector_size_from_config(vectors_config.get(self.vector_name))

        if hasattr(vectors_config, "size"):
            return int(vectors_config.size)

        if isinstance(vectors_config, dict):
            if "size" in vectors_config:
                return int(vectors_config["size"])
            for value in vectors_config.values():
                nested_size = self._vector_size_from_config(value)
                if nested_size:
                    return nested_size

        return None

    def _raise_qdrant_access_error(self, exc: UnexpectedResponse) -> None:
        status_code = self._unexpected_status_code(exc)

        if status_code == 403:
            raise PermissionError(
                "Qdrant returned 403 Forbidden while checking collection "
                f"{self.collection_name!r}. Verify QDRANT_API_KEY belongs to this cluster, "
                "has read/write access to this collection, and that the collection exists if "
                "you are using a collection-scoped key. To let this pipeline create the "
                "collection, use a cluster-level/admin key or create the collection first."
            ) from None

        if status_code == 404:
            return

        raise exc

    def _unexpected_status_code(self, exc: UnexpectedResponse) -> int | None:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        message = str(exc)
        if "403" in message:
            return 403
        if "404" in message:
            return 404
        return None
