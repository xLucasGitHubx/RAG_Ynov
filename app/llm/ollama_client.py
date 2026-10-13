"""Client Ollama : LLM quantifié (GGUF) servi en local, sans consommer de minutes ZeroGPU.

Ollama tourne dans un conteneur Docker (voir docker-compose.yml) et expose l'API /api/chat.
"""

import json
import logging
from collections.abc import Iterator

import httpx

from app.llm.base import Generation, LLMError

logger = logging.getLogger("rag.llm.ollama")


class OllamaClient:
    name = "ollama"

    def __init__(self, base_url: str, model: str, temperature: float, max_tokens: int,
                 timeout_s: int, num_ctx: int = 8192) -> None:
        self.model = model
        self.url = base_url.rstrip("/") + "/api/chat"
        self.options = {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx}
        self.timeout = httpx.Timeout(timeout_s, connect=5)

    def _payload(self, system_prompt: str, user_prompt: str, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": stream,
            "options": self.options,
            "keep_alive": "30m",
        }

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        try:
            response = httpx.post(self.url, json=self._payload(system_prompt, user_prompt, False),
                                  timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Échec de l'appel Ollama : %s", type(exc).__name__)
            raise LLMError(f"Erreur Ollama ({self.url}) : {exc}") from exc

        text = (data.get("message") or {}).get("content", "").strip()
        if not text:
            raise LLMError("Réponse vide d'Ollama.")
        logger.info("Ollama %s : %s tokens en entrée, %s en sortie", self.model,
                    data.get("prompt_eval_count"), data.get("eval_count"))
        return Generation(text, data.get("prompt_eval_count"), data.get("eval_count"))

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        payload = self._payload(system_prompt, user_prompt, True)
        try:
            with httpx.stream("POST", self.url, json=payload, timeout=self.timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise LLMError(f"Erreur Ollama : {data['error']}")
                    if piece := (data.get("message") or {}).get("content"):
                        yield piece
                    if data.get("done"):
                        logger.info("Ollama %s (stream) : %s tokens en entrée, %s en sortie",
                                    self.model, data.get("prompt_eval_count"),
                                    data.get("eval_count"))
        except httpx.HTTPError as exc:
            logger.error("Échec du streaming Ollama : %s", type(exc).__name__)
            raise LLMError(f"Erreur Ollama ({self.url}) : {exc}") from exc
