"""Client du Space Gradio ZeroGPU (Hugging Face) qui héberge le LLM en production.

Le Space (voir space/app.py) expose une fonction `generate(system_prompt, user_prompt)` décorée
`@spaces.GPU`. L'appel est authentifié avec le HF_TOKEN d'un membre de l'organisation de l'école :
le quota ZeroGPU est décompté sur ce compte.

Non testé en conditions réelles pour l'instant (périmètre local) : à valider à l'itération 4 bis.
"""

import logging
from collections.abc import Iterator

from app.llm.base import Generation, LLMError

logger = logging.getLogger("rag.llm.zerogpu")


class ZeroGPUClient:
    name = "zerogpu"

    def __init__(self, space_id: str, hf_token: str, model: str = "space") -> None:
        from gradio_client import Client  # dépendance optionnelle : pip install gradio_client

        self.model = model
        self.space_id = space_id
        try:
            self._client = Client(space_id, token=hf_token)
        except TypeError:  # anciennes versions de gradio_client
            self._client = Client(space_id, hf_token=hf_token)

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        try:
            text = self._client.predict(system_prompt, user_prompt, api_name="/generate")
        except Exception as exc:  # quota épuisé, file d'attente, Space en veille...
            logger.error("Échec de l'appel ZeroGPU : %s", type(exc).__name__)
            raise LLMError(f"Erreur du Space {self.space_id} : {exc}") from exc
        if not text:
            raise LLMError("Réponse vide du Space ZeroGPU.")
        return Generation(str(text).strip())

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Le Space renvoie le texte cumulé à chaque étape : on n'émet que la partie nouvelle."""
        try:
            job = self._client.submit(system_prompt, user_prompt, api_name="/generate")
            previous = ""
            for partial in job:
                partial = str(partial)
                if partial.startswith(previous):
                    yield partial[len(previous):]
                previous = partial
        except Exception as exc:
            logger.error("Échec du streaming ZeroGPU : %s", type(exc).__name__)
            raise LLMError(f"Erreur du Space {self.space_id} : {exc}") from exc
