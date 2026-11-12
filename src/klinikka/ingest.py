"""Indeksoi tietopohjan Chromaan.

Aja:  uv run python -m klinikka.ingest
"""

from __future__ import annotations

from klinikka.chunking import load_chunks
from klinikka.config import KNOWLEDGE_BASE_DIR, Settings
from klinikka.retrieval import AzureEmbedder, Retriever

EMBEDDING_PRICE_PER_M = 0.02  # text-embedding-3-small, USD / 1M tokenia (tarkista Azuresta)


def main() -> None:
    chunks = load_chunks(KNOWLEDGE_BASE_DIR)
    embedder = AzureEmbedder(Settings.from_env())
    retriever = Retriever(embedder)
    retriever.rebuild(chunks)

    sources = len({c.source for c in chunks})
    cost = embedder.tokens_used * EMBEDDING_PRICE_PER_M / 1_000_000
    print(f"Indeksoitu {len(chunks)} palaa {sources} dokumentista.")
    print(f"Upotustokenit: {embedder.tokens_used}  ->  {cost * 100:.4f} senttiä (USD)")


if __name__ == "__main__":
    main()
