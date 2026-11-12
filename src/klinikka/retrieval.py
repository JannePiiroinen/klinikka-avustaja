"""Hybridihaku: vektorihaku (Chroma) + avainsanahaku (BM25), yhdistetty RRF:llä.

Vektorihaku löytää merkitykseltään samankaltaiset kohdat ("paljonko maksaa" ~ "hinnasto"),
mutta voi ohittaa lyhyen sivumaininnan pitkän kappaleen keskellä. Avainsanahaku löytää
tarkat termit ("laboratorio", "kerroksessa"). Tulokset yhdistetään Reciprocal Rank
Fusionilla, joka ei vaadi pisteiden skaalausta.

Upotusmalli on rajapinnan (Embedder) takana, joten testit voivat käyttää
paikallista korvaajaa ilman API-kutsuja, ja Azuren voi vaihtaa toiseen
tarjoajaan muuttamatta hakulogiikkaa.
"""

from __future__ import annotations

import math
import re
from collections import Counter
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
    score: float  # RRF-pisteet: suurempi = osuvampi


def tokenize(text: str, stem_len: int = 5) -> list[str]:
    """Kevyt suomen "typistys": sanat katkaistaan viiteen merkkiin, jolloin taivutusmuodot
    osuvat yhteen (laboratorio / laboratorion -> "labor", kerros / kerroksessa -> "kerro")."""
    return [w[:stem_len] for w in re.findall(r"\w+", text.lower()) if len(w) > 1]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in docs]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df = Counter(term for doc in self.docs for term in doc)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        result = []
        for doc, length in zip(self.docs, self.lengths, strict=True):
            score = 0.0
            for t in terms:
                if t in doc:
                    tf = doc[t]
                    norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                    score += self.idf[t] * tf * (self.k1 + 1) / norm
            result.append(score)
        return result


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank + 1)
    return fused


class Retriever:
    def __init__(self, embedder: Embedder, path: Path = CHROMA_DIR):
        self._embedder = embedder
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )
        self._load_lexical_index()

    def _load_lexical_index(self) -> None:
        data = self._collection.get(include=["documents", "metadatas"])
        self._ids: list[str] = data["ids"]
        self._docs = {cid: doc for cid, doc in zip(data["ids"], data["documents"], strict=True)}
        self._metas = {cid: m for cid, m in zip(data["ids"], data["metadatas"], strict=True)}
        self._bm25 = BM25([self._docs[cid] for cid in self._ids])

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
        self._load_lexical_index()

    def search(self, query: str, k: int = 6, candidates: int = 20) -> list[SearchHit]:
        if self.count() == 0:
            raise RuntimeError("Hakuindeksi on tyhjä. Aja ensin: uv run python -m klinikka.ingest")
        n = min(candidates, self.count())
        vector = self._collection.query(
            query_embeddings=self._embedder.embed([query]), n_results=n
        )["ids"][0]
        bm25_scores = self._bm25.scores(query)
        lexical = [
            cid
            for cid, score in sorted(zip(self._ids, bm25_scores, strict=True), key=lambda x: -x[1])
            if score > 0
        ][:n]
        fused = reciprocal_rank_fusion([vector, lexical])
        top = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [
            SearchHit(
                chunk_id=cid,
                source=self._metas[cid]["source"],
                label=self._metas[cid]["label"],
                text=self._docs[cid],
                score=score,
            )
            for cid, score in top
        ]
