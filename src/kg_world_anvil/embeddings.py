"""OpenAI embedding helpers for entity dedup and RAG retrieval."""

from __future__ import annotations

from openai import OpenAI

from kg_world_anvil.config import Settings, get_settings


class EmbeddingClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = None
        if self.settings.openai_api_key:
            self._client = OpenAI(api_key=self.settings.openai_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    def embed_text(self, text: str) -> list[float]:
        if not self._client:
            return []
        response = self._client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self._client or not texts:
            return []
        response = self._client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=texts,
        )
        sorted_data = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in sorted_data]
