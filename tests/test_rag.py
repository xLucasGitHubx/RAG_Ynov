"""Tests du retriever et de l'assistant avec de faux composants (aucun modèle chargé)."""

from fastapi.testclient import TestClient

from app.llm import Generation
from app.main import app, assistant_dependency
from app.prompts import REFUSAL, is_refusal
from app.rag.retriever import RetrievedChunk, Retriever, SearchResult
from app.services.assistant import Assistant, build_sources
from eval.common import first_hit_rank, mrr_at_k, recall_at_k


class FakeEmbedder:
    model_name = "fake"

    def embed_query(self, text):
        return [1.0, 0.0]


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows  # (id, texte, métadonnées, distance)
        self.last_where = None

    def count(self):
        return len(self.rows)

    def query(self, query_embeddings, n_results, where, include):
        self.last_where = where
        rows = self.rows[:n_results]
        return {
            "ids": [[r[0] for r in rows]],
            "documents": [[r[1] for r in rows]],
            "metadatas": [[r[2] for r in rows]],
            "distances": [[r[3] for r in rows]],
        }


class FakeReranker:
    def score(self, query, passages):
        # Le passage qui contient « télétravail » est jugé le plus pertinent.
        return [0.9 if "télétravail" in p else 0.01 for p in passages]


def meta(document, section="S", page=1):
    return {"document": document, "section": section, "page": page, "titre": document,
            "n_tokens": 10}


ROWS = [
    ("a", "Doc > S\n\nCongés payés", meta("conges.pdf", "Congés"), 0.2),
    ("b", "Doc > S\n\nRègles de télétravail", meta("teletravail.docx", "Télétravail"), 0.3),
]


def test_retriever_exclut_les_versions_obsoletes():
    collection = FakeCollection(ROWS)
    Retriever(collection, FakeEmbedder(), exclude_obsolete=True).search("q")
    assert collection.last_where == {"statut": {"$ne": "obsolete"}}


def test_retriever_reclasse_et_filtre_avec_le_reranker():
    retriever = Retriever(FakeCollection(ROWS), FakeEmbedder(), FakeReranker(),
                          top_k=5, min_rerank_score=0.05)
    result = retriever.search("télétravail ?")
    assert [c.id for c in result.chunks] == ["b"]
    assert result.candidates == 2
    assert {"embedding", "vector_search", "rerank"} <= set(result.timings_ms)


def test_retriever_sans_reranker_garde_l_ordre_vectoriel():
    result = Retriever(FakeCollection(ROWS), FakeEmbedder(), top_k=1).search("q")
    assert [c.id for c in result.chunks] == ["a"]
    assert round(result.chunks[0].score, 2) == 0.8


class SpyLLM:
    name, model = "espion", "espion"

    def __init__(self, answer="Réponse [teletravail.docx]"):
        self.answer = answer
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append(user_prompt)
        return Generation(self.answer, 100, 10)

    def stream(self, system_prompt, user_prompt):
        self.calls.append(user_prompt)
        yield from ["Réponse ", "[teletravail.docx]"]


class StubRetriever:
    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, question):
        return SearchResult(self.chunks, {"embedding": 1.0})


CHUNKS = [RetrievedChunk(r[0], r[1], r[2], 1 - r[3], 0.8) for r in ROWS]


def test_assistant_refuse_sans_appeler_le_llm_si_rien_n_est_trouve():
    llm = SpyLLM()
    result = Assistant(llm, StubRetriever([])).answer("Cours de l'action ?")
    assert result.refused and not result.llm_called
    assert result.response.answer.startswith(REFUSAL)
    assert llm.calls == []


def test_assistant_envoie_les_extraits_et_ne_garde_que_les_sources_citees():
    llm = SpyLLM()
    result = Assistant(llm, StubRetriever(CHUNKS)).answer("Télétravail ?")
    assert "[Extrait 1] Document : conges.pdf, page 1" in llm.calls[0]
    assert "<question>\nTélétravail ?\n</question>" in llm.calls[0]
    assert [s.document for s in result.response.sources] == ["teletravail.docx"]
    assert result.prompt_tokens == 100
    assert "llm" in result.timings_ms


def test_assistant_masque_les_sources_quand_le_llm_refuse():
    llm = SpyLLM(answer=f"{REFUSAL} Contactez les RH.")
    result = Assistant(llm, StubRetriever(CHUNKS)).answer("?")
    assert result.refused
    assert result.response.sources == []


def test_build_sources_deduplique_et_tronque_l_extrait():
    long_chunk = RetrievedChunk("c", "Doc > S\n\n" + "x" * 500, meta("a.pdf", page=-1), 0.5)
    sources = build_sources([long_chunk, long_chunk])
    assert len(sources) == 1
    assert sources[0].page is None
    assert sources[0].extrait.endswith("…") and len(sources[0].extrait) == 301


def test_is_refusal_detecte_la_phrase_de_refus():
    assert is_refusal(f"{REFUSAL} Vous pouvez contacter le service RH.")
    assert not is_refusal("Vous avez droit à 27 jours de congés [guide_conges_absences.pdf].")


def test_endpoint_stream_envoie_sources_tokens_puis_done():
    app.dependency_overrides[assistant_dependency] = lambda: Assistant(SpyLLM(),
                                                                       StubRetriever(CHUNKS))
    try:
        with TestClient(app) as client:
            response = client.post("/ask/stream", json={"question": "Télétravail ?"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [block.split("\n")[0] for block in response.text.strip().split("\n\n")]
    assert events[0] == "event: sources"
    assert events.count("event: token") == 2
    assert events[-1] == "event: done"
    assert '"document": "teletravail.docx"' in response.text.split("event: done")[1]


def test_endpoint_ask_renvoie_l_en_tete_server_timing():
    app.dependency_overrides[assistant_dependency] = lambda: Assistant(SpyLLM(),
                                                                       StubRetriever(CHUNKS))
    try:
        response = TestClient(app).post("/ask", json={"question": "Télétravail ?"})
    finally:
        app.dependency_overrides.clear()
    assert "llm;dur=" in response.headers["server-timing"]
    assert "total;dur=" in response.headers["server-timing"]


def test_metriques_de_retrieval():
    ranks = [1, 3, None, 6]
    assert first_hit_rank([False, False, True]) == 3
    assert first_hit_rank([False]) is None
    assert recall_at_k(ranks, 5) == 0.5
    assert round(mrr_at_k(ranks, 10), 4) == round((1 + 1 / 3 + 1 / 6) / 4, 4)


def test_retriever_ne_renvoie_rien_si_le_meilleur_score_est_trop_bas():
    # Distances 0,2 et 0,3 -> similarités 0,8 et 0,7.
    def search(min_score):
        return Retriever(FakeCollection(ROWS), FakeEmbedder(), min_score=min_score).search("q")

    assert search(0.9).chunks == []
    assert len(search(0.75).chunks) == 2


def test_une_reponse_qui_cite_un_document_n_est_pas_un_refus():
    answer = f"{REFUSAL} Cependant, l'indemnité est de 2,50 € [accord_teletravail_2025.docx]."
    assert not is_refusal(answer)
