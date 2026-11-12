"""Hybridihaun testit: BM25, RRF ja kierroksella 1–2 löydetty f14-hakuvirhe."""

from __future__ import annotations

from klinikka.chunking import load_chunks
from klinikka.config import KNOWLEDGE_BASE_DIR
from klinikka.retrieval import BM25, Retriever, reciprocal_rank_fusion, tokenize

F14_QUERY = "Missä kerroksessa laboratorio on?"
F14_FACT = "Laboratorio ja kuvantaminen ovat 1. kerroksessa"


def test_tokenize_merges_finnish_inflections():
    assert tokenize("laboratorio laboratorion laboratorioon") == ["labor"] * 3
    assert tokenize("kerros kerroksessa kerroksiin") == ["kerro"] * 3


def test_bm25_ranks_exact_terms_first():
    bm25 = BM25(["Hinnasto: PVK 19 €", "Laboratorio on 1. kerroksessa", "Pysäköinti pihassa"])
    scores = bm25.scores(F14_QUERY)
    assert scores.index(max(scores)) == 1


def test_rrf_rewards_items_ranked_high_in_both_lists():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert set(fused) == {"a", "b", "c", "d"}
    assert fused["a"] == fused["b"] > fused["c"]


def test_f14_keyword_search_ranks_the_floor_fact_first():
    """Kierroksella 2 pelkkä vektorihaku ei löytänyt tätä. Avainsanahaku nostaa sen kärkeen."""
    chunks = load_chunks(KNOWLEDGE_BASE_DIR)
    scores = BM25([c.text for c in chunks]).scores(F14_QUERY)
    best = chunks[scores.index(max(scores))]
    assert F14_FACT in best.text


def test_f14_hybrid_search_returns_the_floor_fact(retriever):
    hits = retriever.search(F14_QUERY, k=6)
    assert any(F14_FACT in h.text for h in hits)


def test_retriever_reloads_lexical_index_from_disk(tmp_path, retriever):
    class Embedder:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    Retriever(Embedder(), path=tmp_path).rebuild(load_chunks(KNOWLEDGE_BASE_DIR))
    reopened = Retriever(Embedder(), path=tmp_path)  # kuten ask/evaluate käynnistyessä
    assert reopened._bm25.scores(F14_QUERY) != [0.0] * reopened.count()
