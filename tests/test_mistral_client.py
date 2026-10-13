"""Tests du client Mistral, avec un faux SDK (aucun appel réseau)."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm import LLMError, LLMNotConfiguredError, build_llm_client
from app.llm.mistral_client import MistralClient


def fake_response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


def make_client(complete):
    client = MistralClient(
        api_key="test", model="mistral-small-latest", temperature=0.1, max_tokens=100, timeout_s=5
    )
    client._client = SimpleNamespace(chat=SimpleNamespace(complete=complete))
    return client


def test_generate_envoie_les_bons_messages_et_renvoie_le_texte():
    calls = {}

    def complete(**kwargs):
        calls.update(kwargs)
        return fake_response("  Vous avez droit à 2 jours.  ")

    generation = make_client(complete).generate("SYSTEME", "QUESTION")

    assert generation.text == "Vous avez droit à 2 jours."
    assert generation.prompt_tokens == 120
    assert generation.completion_tokens == 30
    assert calls["model"] == "mistral-small-latest"
    assert calls["temperature"] == 0.1
    assert calls["messages"][0] == {"role": "system", "content": "SYSTEME"}
    assert calls["messages"][1] == {"role": "user", "content": "QUESTION"}


def test_generate_transforme_les_erreurs_du_sdk_en_llm_error():
    def complete(**kwargs):
        raise RuntimeError("401 Unauthorized")

    with pytest.raises(LLMError):
        make_client(complete).generate("s", "u")


def test_generate_refuse_une_reponse_vide():
    with pytest.raises(LLMError):
        make_client(lambda **kw: fake_response("")).generate("s", "u")


def test_factory_exige_une_cle_pour_mistral():
    with pytest.raises(LLMNotConfiguredError):
        build_llm_client(Settings(llm_provider="mistral", mistral_api_key=None, _env_file=None))


def test_factory_construit_le_client_mistral_avec_une_cle():
    client = build_llm_client(
        Settings(llm_provider="mistral", mistral_api_key="cle-test", _env_file=None)
    )
    assert client.name == "mistral"
    assert client.model == "mistral-small-latest"
