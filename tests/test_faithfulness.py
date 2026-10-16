"""Contrôle de fidélité après génération : un contrôle, une nouvelle tentative au plus."""

from fastapi.testclient import TestClient

from app.llm import Generation, LLMError
from app.main import app, assistant_dependency
from app.prompts import REFUSAL, parse_verdict
from app.services.assistant import Assistant
from tests.test_rag import CHUNKS, StubRetriever

FIDELE = "VERDICT: FIDELE\nMOTIF: aucun"
NON_FIDELE = "VERDICT: NON_FIDELE\nMOTIF: le chiffre de 30 jours est absent des extraits"
INITIALE = "Vous avez 30 jours [teletravail.docx]."
CORRIGEE = "Le télétravail est limité à 2 jours par semaine [teletravail.docx]."


class ScriptedLLM:
    """Renvoie les réponses dans l'ordre ; une exception de la liste est levée."""

    name, model = "script", "script"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Generation(reply, 100, 10)

    def stream(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        yield from ["Vous avez ", "30 jours [teletravail.docx]."]


def answer(llm, verify=True):
    return Assistant(llm, StubRetriever(CHUNKS), verify=verify).answer("Télétravail ?")


def test_parse_verdict():
    assert parse_verdict(FIDELE) == (True, "aucun")
    assert parse_verdict("verdict : fidèle") == (True, "")
    assert parse_verdict(NON_FIDELE)[0] is False
    assert parse_verdict("verdict: non fidèle\nmotif: chiffre faux") == (False, "chiffre faux")
    assert parse_verdict("je ne sais pas") == (None, "")


def test_reponse_fidele_deux_appels_sans_nouvelle_tentative():
    llm = ScriptedLLM(INITIALE, FIDELE)
    result = answer(llm)
    assert result.response.answer == INITIALE
    assert result.faithfulness == "ok"
    assert len(llm.calls) == 2
    assert "<reponse>\n" + INITIALE in llm.calls[1][1]
    assert "check" in result.timings_ms and "retry" not in result.timings_ms
    assert result.prompt_tokens == 200 and result.completion_tokens == 20


def test_reponse_non_fidele_une_seule_nouvelle_tentative_avec_le_motif():
    llm = ScriptedLLM(INITIALE, NON_FIDELE, CORRIGEE)
    result = answer(llm)
    assert result.response.answer == CORRIGEE
    assert result.faithfulness == "retried"
    assert len(llm.calls) == 3  # pas de second contrôle
    assert "30 jours est absent" in llm.calls[2][1] and INITIALE in llm.calls[2][1]
    assert "retry" in result.timings_ms
    assert [s.document for s in result.response.sources] == ["teletravail.docx"]


def test_nouvelle_tentative_qui_refuse_masque_les_sources():
    llm = ScriptedLLM(INITIALE, NON_FIDELE, REFUSAL)
    result = answer(llm)
    assert result.refused and result.response.sources == []


def test_verdict_illisible_garde_la_reponse():
    llm = ScriptedLLM(INITIALE, "Je ne sais pas.")
    result = answer(llm)
    assert result.response.answer == INITIALE
    assert result.faithfulness == "unreadable" and len(llm.calls) == 2


def test_panne_du_controle_garde_la_reponse():
    llm = ScriptedLLM(INITIALE, LLMError("Space en veille"))
    result = answer(llm)
    assert result.response.answer == INITIALE
    assert result.faithfulness == "error"


def test_panne_de_la_nouvelle_tentative_garde_la_reponse_initiale():
    llm = ScriptedLLM(INITIALE, NON_FIDELE, LLMError("quota épuisé"))
    result = answer(llm)
    assert result.response.answer == INITIALE
    assert result.faithfulness == "error"


def test_un_refus_n_est_pas_controle():
    llm = ScriptedLLM(f"{REFUSAL} Contactez les RH.")
    result = answer(llm)
    assert result.refused and result.faithfulness == "skipped" and len(llm.calls) == 1


def test_controle_desactive_un_seul_appel():
    llm = ScriptedLLM(INITIALE)
    result = answer(llm, verify=False)
    assert result.faithfulness == "skipped" and len(llm.calls) == 1


def test_stream_done_porte_la_reponse_corrigee():
    llm = ScriptedLLM(NON_FIDELE, CORRIGEE)  # stream() fournit la réponse initiale
    app.dependency_overrides[assistant_dependency] = lambda: Assistant(
        llm, StubRetriever(CHUNKS), verify=True)
    try:
        with TestClient(app) as client:
            response = client.post("/ask/stream", json={"question": "Télétravail ?"})
    finally:
        app.dependency_overrides.clear()
    done = response.text.split("event: done")[1]
    assert "2 jours par semaine" in done
    assert "30 jours" not in done
