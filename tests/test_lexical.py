"""Tests de la recherche lexicale BM25 et de la fusion RRF."""

from app.rag.lexical import Analyzer, BM25Index, reciprocal_rank_fusion
from app.rag.retriever import Retriever
from tests.test_rag import FakeCollection, FakeEmbedder, meta

TEXTS = {
    "conges": "Guide > Événements familiaux\n\nDéménagement : 1 jour ouvré par an.",
    "syntec": "Convention > Changement de résidence\n\nLe salarié muté change de résidence.",
    "astreinte": "Accord > Astreintes\n\nIndemnité de 150 euros par semaine d'astreinte.",
    "ancien": "Accord 2023 > Astreintes\n\nIndemnité de 100 euros par semaine d'astreinte.",
}


def index() -> BM25Index:
    metas = [meta(f"{k}.pdf") | {"statut": "obsolete" if k == "ancien" else "en_vigueur"}
             for k in TEXTS]
    return BM25Index(list(TEXTS), list(TEXTS.values()), metas)


def test_l_analyseur_racinise_et_retire_accents_et_mots_vides():
    tokens = Analyzer()("Puis-je déménager ? Le déménagement")
    assert tokens.count("demenag") == 2
    assert "le" not in tokens


def test_bm25_trouve_le_mot_exact_malgre_la_conjugaison():
    hits = index().search("Ai-je droit à un jour pour déménager ?", n=3)
    assert hits[0].id == "conges"


def test_bm25_exclut_les_documents_obsoletes():
    ids = [h.id for h in index().search("astreinte", n=5)]
    assert ids == ["astreinte"]
    assert "ancien" in [h.id for h in index().search("astreinte", n=5, exclude_obsolete=False)]


def test_rrf_favorise_les_documents_bien_classes_partout():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]])
    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c", "d"}


class CollectionWithEmbeddings(FakeCollection):
    def count(self):
        return len(TEXTS)  # même corpus que l'index BM25

    def get(self, ids, include):
        return {"ids": ids, "embeddings": [[0.5, 0.0] for _ in ids]}


def test_la_recherche_hybride_ajoute_les_chunks_trouves_par_bm25():
    # La recherche vectorielle ne renvoie que « syntec » ; BM25 apporte « conges ».
    collection = CollectionWithEmbeddings([("syntec", TEXTS["syntec"], meta("syntec.md"), 0.3)])
    retriever = Retriever(collection, FakeEmbedder(), top_k=2, lexical=index())
    result = retriever.search("déménagement")
    ids = [c.id for c in result.chunks]
    assert "conges" in ids
    added = next(c for c in result.chunks if c.id == "conges")
    assert added.score == 0.5  # cosinus recalculé à partir de l'embedding stocké
    assert "lexical_search" in result.timings_ms
