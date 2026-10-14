"""Tests du client ZeroGPU avec un faux gradio_client (aucun appel réseau ni minute GPU)."""

import json

import gradio_client
import pytest

from app.config import Settings
from app.llm import LLMError, LLMNotConfiguredError, build_llm_client
from app.llm.zerogpu_client import ZeroGPUClient


class FakeGradioClient:
    calls: list = []

    def __init__(self, space_id, token=None, verbose=True):
        self.space_id = space_id
        self.token = token

    def predict(self, *args, api_name):
        FakeGradioClient.calls.append((api_name, args))
        return json.dumps({"text": "27 jours ouvrés [guide_conges_absences.pdf]",
                           "prompt_tokens": 1500, "completion_tokens": 20,
                           "generation_seconds": 1.2, "model": "ministral"})

    def submit(self, *args, api_name):
        FakeGradioClient.calls.append((api_name, args))
        return iter(["27", "27 jours", "27 jours", "27 jours ouvrés"])


@pytest.fixture
def client(monkeypatch):
    FakeGradioClient.calls = []
    monkeypatch.setattr(gradio_client, "Client", FakeGradioClient)
    return ZeroGPUClient("Lulu18/rag-llm", "hf_test")


def test_generate_utilise_le_point_json_et_renvoie_les_tokens(client):
    generation = client.generate("SYS", "QUESTION")
    assert generation.text.startswith("27 jours")
    assert (generation.prompt_tokens, generation.completion_tokens) == (1500, 20)
    assert FakeGradioClient.calls == [("/generate_json", ("SYS", "QUESTION"))]


def test_stream_n_emet_que_la_partie_nouvelle_du_texte_cumule(client):
    assert list(client.stream("s", "u")) == ["27", " jours", " ouvrés"]
    assert FakeGradioClient.calls[0][0] == "/generate"


def test_les_erreurs_du_space_deviennent_des_llm_error(client, monkeypatch):
    def boom(*args, api_name):
        raise RuntimeError("ZeroGPU quota exceeded")

    monkeypatch.setattr(client._client, "predict", boom)
    with pytest.raises(LLMError, match="quota"):
        client.generate("s", "u")


def test_factory_exige_token_et_space():
    with pytest.raises(LLMNotConfiguredError):
        build_llm_client(Settings(llm_provider="zerogpu", hf_token=None, llm_space_id=None,
                                  _env_file=None))


def test_factory_construit_le_client_zerogpu(monkeypatch):
    monkeypatch.setattr(gradio_client, "Client", FakeGradioClient)
    llm = build_llm_client(Settings(llm_provider="zerogpu", hf_token="hf_x",
                                    llm_space_id="Lulu18/rag-llm", _env_file=None))
    assert (llm.name, llm.space_id) == ("zerogpu", "Lulu18/rag-llm")
