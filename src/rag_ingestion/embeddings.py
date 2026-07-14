from __future__ import annotations

import logging
import os

from langchain_openai import OpenAIEmbeddings
from tenacity import retry, stop_after_attempt, wait_exponential

from rag_ingestion.config import Settings
from rag_ingestion.models import ChunkRecord
from rag_ingestion.utils import batched

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    def __init__(self, settings: Settings) -> None:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
        self.batch_size = settings.embedding_batch_size
        self.client = OpenAIEmbeddings(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    def embed_chunks(self, chunks: list[ChunkRecord]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for batch_number, batch in enumerate(batched(chunks, self.batch_size), start=1):
            logger.info("Embedding batch %s (%s chunk(s))", batch_number, len(batch))
            embeddings.extend(self._embed_texts([chunk.text for chunk in batch]))
        return embeddings

    @retry(wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(5), reraise=True)
    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(texts)
