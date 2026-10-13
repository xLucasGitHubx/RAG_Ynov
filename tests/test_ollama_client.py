"""Tests du client Ollama avec un faux serveur HTTP (httpx.MockTransport)."""

import json

import httpx
import pytest

from app.config import Settings
from app.llm import LLMError, build_llm_client
from app.llm.ollama_client import OllamaClient


@pytest.fixture
def client():
    return OllamaClient("http://ollama:11434", "ministral-3:3b", 0.1, 100, 5, num_ctx=4096)


def mock(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def post(url, **kwargs):
        timeout = kwargs.pop("timeout", None)
        with real_client(transport=transport, timeout=timeout) as c:
            return c.post(url, **kwargs)

    def stream(method, url, **kwargs):
        timeout = kwargs.pop("timeout", None)
        c = real_client(transport=transport, timeout=timeout)
        return c.stream(method, url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "stream", stream)


def test_generate_envoie_le_bon_payload(monkeypatch, client):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": " 27 jours. "},
                                         "prompt_eval_count": 800, "eval_count": 12})

    mock(monkeypatch, handler)
    generation = client.generate("SYS", "USER")
    assert generation.text == "27 jours."
    assert (generation.prompt_tokens, generation.completion_tokens) == (800, 12)
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["options"] == {"temperature": 0.1, "num_predict": 100, "num_ctx": 4096}
    assert seen["stream"] is False


def test_stream_renvoie_les_morceaux(monkeypatch, client):
    lines = [{"message": {"content": "Bon"}}, {"message": {"content": "jour"}},
             {"message": {"content": ""}, "done": True, "eval_count": 2}]
    body = "\n".join(json.dumps(line) for line in lines)
    mock(monkeypatch, lambda request: httpx.Response(200, text=body))
    assert list(client.stream("s", "u")) == ["Bon", "jour"]


def test_les_erreurs_http_deviennent_des_llm_error(monkeypatch, client):
    mock(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(LLMError):
        client.generate("s", "u")


def test_factory_construit_ollama():
    llm = build_llm_client(Settings(llm_provider="ollama", ollama_model="qwen3:4b",
                                    _env_file=None))
    assert (llm.name, llm.model) == ("ollama", "qwen3:4b")
