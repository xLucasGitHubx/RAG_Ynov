"""Client de l'API Mistral (SDK officiel mistralai v3)."""

import logging
from collections.abc import Iterator

from mistralai.client import Mistral

from app.llm.base import Generation, LLMError

logger = logging.getLogger("rag.llm.mistral")


class MistralClient:
    name = "mistral"

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: int,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = Mistral(api_key=api_key, timeout_ms=timeout_s * 1000)

    def _messages(self, system_prompt: str, user_prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        try:
            response = self._client.chat.complete(
                model=self.model,
                messages=self._messages(system_prompt, user_prompt),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:  # erreurs réseau, clé invalide, quota, modèle inconnu...
            logger.error("Échec de l'appel Mistral : %s", type(exc).__name__)
            raise LLMError(f"Erreur de l'API Mistral : {exc}") from exc

        if not response.choices:
            raise LLMError("Réponse vide de l'API Mistral.")

        content = response.choices[0].message.content
        if isinstance(content, list):  # contenu multi-parties : on garde le texte
            content = "".join(getattr(part, "text", "") or "" for part in content)
        if not content:
            raise LLMError("Réponse vide de l'API Mistral.")

        usage = response.usage
        if usage:
            logger.info(
                "Mistral %s : %s tokens en entrée, %s en sortie",
                self.model,
                usage.prompt_tokens,
                usage.completion_tokens,
            )
        return Generation(
            content.strip(),
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
        )

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        try:
            events = self._client.chat.stream(
                model=self.model,
                messages=self._messages(system_prompt, user_prompt),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            for event in events:
                choices = event.data.choices
                if choices and (piece := choices[0].delta.content):
                    yield piece if isinstance(piece, str) else "".join(
                        getattr(part, "text", "") or "" for part in piece
                    )
        except Exception as exc:
            logger.error("Échec du streaming Mistral : %s", type(exc).__name__)
            raise LLMError(f"Erreur de l'API Mistral : {exc}") from exc
