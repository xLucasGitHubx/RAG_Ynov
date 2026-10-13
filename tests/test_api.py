"""Tests de l'API."""

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.llm import Generation, LLMError
from app.main import app, assistant_dependency, get_assistant
from app.services.assistant import Assistant

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()
    get_assistant.cache_clear()


def test_health_renvoie_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["llm_provider"] == "static"


def test_ask_renvoie_la_reponse_du_llm():
    response = client.post("/ask", json={"question": "Combien de jours de congés ai-je ?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Bonjour, je suis l'assistant RH"
    assert body["sources"] == []


def test_ask_transmet_la_question_au_llm():
    class EspionLLM:
        name, model = "espion", "espion"

        def __init__(self):
            self.prompts = []

        def generate(self, system_prompt, user_prompt):
            self.prompts.append((system_prompt, user_prompt))
            return Generation("ok")

    espion = EspionLLM()
    app.dependency_overrides[assistant_dependency] = lambda: Assistant(espion)
    client.post("/ask", json={"question": "Où trouver le VPN ?"})

    system_prompt, user_prompt = espion.prompts[0]
    assert "UNIQUEMENT" in system_prompt
    assert "Où trouver le VPN ?" in user_prompt
    assert "<documents>" in user_prompt


def test_ask_renvoie_502_si_le_llm_echoue():
    class LLMEnPanne:
        name, model = "panne", "panne"

        def generate(self, system_prompt, user_prompt):
            raise LLMError("timeout")

    app.dependency_overrides[assistant_dependency] = lambda: Assistant(LLMEnPanne())
    response = client.post("/ask", json={"question": "Bonjour"})
    assert response.status_code == 502


def test_ask_renvoie_503_si_la_cle_mistral_manque(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    # Chaîne vide plutôt que suppression : une variable d'environnement prime sur le .env local.
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.post("/ask", json={"question": "Bonjour"})
        assert response.status_code == 503
        assert "MISTRAL_API_KEY" in response.json()["detail"]
    finally:
        monkeypatch.setenv("LLM_PROVIDER", "static")
        get_settings.cache_clear()


def test_ask_refuse_une_question_vide():
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_ask_refuse_un_corps_sans_question():
    assert client.post("/ask", json={}).status_code == 422


def test_ask_refuse_une_question_trop_longue():
    assert client.post("/ask", json={"question": "a" * 2001}).status_code == 422


def test_swagger_est_disponible():
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_racine_redirige_vers_swagger():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"
