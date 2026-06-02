"""Retrieval-augmented natural language answers over document chunks."""

from __future__ import annotations

from openai import OpenAI

from kg_world_anvil.config import Settings, get_settings
from kg_world_anvil.db.repository import GraphRepository
from kg_world_anvil.embeddings import EmbeddingClient
from kg_world_anvil.models import RAGAnswer, RAGCitation


class RAGService:
    def __init__(
        self,
        repo: GraphRepository,
        settings: Settings | None = None,
    ) -> None:
        self.repo = repo
        self.settings = settings or get_settings()
        self.embeddings = EmbeddingClient(self.settings)
        self._client: OpenAI | None = None
        if self.settings.openai_api_key:
            self._client = OpenAI(api_key=self.settings.openai_api_key)

    async def answer(self, question: str) -> RAGAnswer:
        if not self.settings.use_embeddings:
            raise RuntimeError("Enable USE_EMBEDDINGS in config to use Ask (RAG) mode.")
        if not self.embeddings.available:
            raise RuntimeError("OpenAI API key is required for embeddings.")
        if not self._client:
            raise RuntimeError("OpenAI API key is required for answer generation.")

        query_vec = self.embeddings.embed_text(question.strip())
        if not query_vec:
            raise RuntimeError("Failed to embed the question.")

        hits = await self.repo.search_chunks(query_vec, k=self.settings.rag_top_k)
        if not hits:
            return RAGAnswer(
                question=question,
                answer="No relevant source passages were found in the knowledge base.",
                citations=[],
            )

        context_blocks: list[str] = []
        citations: list[RAGCitation] = []
        for index, hit in enumerate(hits, start=1):
            context_blocks.append(
                f"[{index}] document={hit.document_id} chunk={hit.seq}\n{hit.text}"
            )
            citations.append(
                RAGCitation(
                    document_id=hit.document_id,
                    seq=hit.seq,
                    snippet=hit.text[:240],
                )
            )

        context = "\n\n---\n\n".join(context_blocks)
        completion = self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You answer questions about a world-building knowledge base using ONLY "
                        "the provided source passages. Cite passages inline as [1], [2], etc. "
                        "If the passages do not contain enough information, say so clearly."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context passages:\n\n{context}\n\nQuestion: {question.strip()}",
                },
            ],
        )
        answer_text = completion.choices[0].message.content or ""
        return RAGAnswer(question=question, answer=answer_text, citations=citations)
