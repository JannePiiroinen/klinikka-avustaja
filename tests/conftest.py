"""Yhteiset testifixturet: paikallinen upotusmalli ja hakuindeksi ilman API-kutsuja."""

from __future__ import annotations

import hashlib
import math
import re

import pytest

from klinikka.chunking import load_chunks
from klinikka.config import KNOWLEDGE_BASE_DIR
from klinikka.retrieval import Retriever


class FakeEmbedder:
    dim = 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in re.findall(r"\w+", text.lower()):
                idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


@pytest.fixture(scope="session")
def retriever(tmp_path_factory) -> Retriever:
    r = Retriever(FakeEmbedder(), path=tmp_path_factory.mktemp("chroma"))
    r.rebuild(load_chunks(KNOWLEDGE_BASE_DIR))
    return r
