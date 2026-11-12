"""Upotukset ja vektorihaku (Chroma).

Upotusmalli on rajapinnan (Embedder) takana, joten testit voivat käyttää
paikallista korvaajaa ilman API-kutsuja, ja Azuren voi vaihtaa toiseen
tarjoajaan muuttamatta hakulogiikkaa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import chromadb

from klinikka.chunking import Chunk
from klinikka.config import PROJECT_ROOT, Settings

CHROMA_DIR = PROJECT_ROOT / "chroma_db"
COLLECTION = "klinikka"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class AzureEmbedder:
    def __init__(self, settings: Settings):
        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            api_version=settings.azure_api_version,
        )
        self._deployment = settings.embedding_deployment
        self.tokens_used = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._deployment, input=texts)
        self.tokens_used += resp.usage.prompt_tokens
        return [item.embedding for item in resp.data]


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    source: str
    label: str
    text: str
    distance: float


class Retriever:
    def __init__(self, embedder: Embedder, path: Path = CHROMA_DIR):
        self._embedder = embedder
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self._collection.count()

    def rebuild(self, chunks: list[Chunk]) -> None:
        """Tyhjentää kokoelman ja indeksoi palat uudelleen."""
        self._client.delete_collection(COLLECTION)
        self._collection = self._client.create_collection(
            COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )
        self._collection.add(
            ids=[c.id for c in chunks],
            embeddings=self._embedder.embed([c.text for c in chunks]),
            documents=[c.text for c in chunks],
            metadatas=[{"source": c.source, "label": c.label} for c in chunks],
        )

    def search(self, query: str, k: int = 6) -> list[SearchHit]:
        if self.count() == 0:
            raise RuntimeError("Hakuindeksi on tyhjä. Aja ensin: uv run python -m klinikka.ingest")
        res = self._collection.query(query_embeddings=self._embedder.embed([query]), n_results=k)
        return [
            SearchHit(
                chunk_id=cid,
                source=meta["source"],
                label=meta["label"],
                text=doc,
                distance=dist,
            )
            for cid, doc, meta, dist in zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
                strict=True,
            )
        ]
