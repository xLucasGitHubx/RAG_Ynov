"""Client du Space Gradio ZeroGPU (Hugging Face) qui héberge le LLM en production.

Le Space (voir space/app.py) expose :
- /generate      : texte en streaming (cumulé), utilisé par l'assistant ;
- /generate_json : réponse complète + mesures (tokens, durée, VRAM), utilisé par les évaluations.

L'appel est authentifié avec HF_TOKEN : le quota ZeroGPU est décompté sur ce compte.
"""

import json
import logging
from collections.abc import Iterator

from app.llm.base import Generation, LLMError

logger = logging.getLogger("rag.llm.zerogpu")


class ZeroGPUClient:
    name = "zerogpu"

    def __init__(self, space_id: str, hf_token: str, model: str | None = None) -> None:
        from gradio_client import Client  # dépendance légère, présente dans requirements.txt

        self.model = model or space_id
        self.space_id = space_id
        try:
            self._client = Client(space_id, token=hf_token, verbose=False)
        except TypeError:  # anciennes versions de gradio_client
            self._client = Client(space_id, hf_token=hf_token, verbose=False)
        except Exception as exc:  # Space en veille, en erreur ou introuvable
            raise LLMError(f"Space {space_id} injoignable : {exc}") from exc

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        metrics = self.measure(system_prompt, user_prompt)
        if not metrics.get("text"):
            raise LLMError("Réponse vide du Space ZeroGPU.")
        meta = {k: v for k, v in metrics.items() if k != "text"}
        return Generation(metrics["text"], metrics.get("prompt_tokens"),
                          metrics.get("completion_tokens"), meta)

    def measure(self, system_prompt: str, user_prompt: str) -> dict:
        """Réponse complète et mesures du GPU (durée, tokens/s, VRAM maximale)."""
        try:
            raw = self._client.predict(system_prompt, user_prompt, api_name="/generate_json")
            metrics = json.loads(raw)
        except Exception as exc:  # quota épuisé, file d'attente, Space en veille...
            logger.error("Échec de l'appel ZeroGPU : %s", type(exc).__name__)
            raise LLMError(f"Erreur du Space {self.space_id} : {exc}") from exc
        logger.info("ZeroGPU %s : %s tokens en entrée, %s en sortie, %.1f s de génération",
                    metrics.get("model"), metrics.get("prompt_tokens"),
                    metrics.get("completion_tokens"), metrics.get("generation_seconds") or 0)
        return metrics

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Le Space renvoie le texte cumulé à chaque étape : on n'émet que la partie nouvelle."""
        try:
            job = self._client.submit(system_prompt, user_prompt, api_name="/generate")
            previous = ""
            for partial in job:
                partial = str(partial)
                if partial.startswith(previous) and len(partial) > len(previous):
                    yield partial[len(previous):]
                previous = partial
        except Exception as exc:
            logger.error("Échec du streaming ZeroGPU : %s", type(exc).__name__)
            raise LLMError(f"Erreur du Space {self.space_id} : {exc}") from exc
