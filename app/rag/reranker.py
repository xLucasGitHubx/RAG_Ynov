"""Reranker (cross-encoder BGE-reranker-v2-m3), exécuté sur CPU.

La recherche vectorielle compare la question et chaque chunk séparément ; le cross-encoder lit
la paire (question, chunk) ensemble, ce qui est plus précis mais plus lent. On ne l'applique donc
qu'aux 20 meilleurs chunks pour n'en garder que 5.
"""

import logging
import math
import os
import time

logger = logging.getLogger("rag.reranker")


class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", max_length: int = 1024,
                 batch_size: int = 8, device: str = "cpu") -> None:
        from sentence_transformers import CrossEncoder

        start = time.perf_counter()
        self.model_name = model_name
        self.batch_size = batch_size
        local_only = os.environ.get("MODELS_LOCAL_ONLY") == "1"
        self._model = CrossEncoder(model_name, device=device, local_files_only=local_only)
        # Ne jamais dépasser la longueur maximale du modèle (512 positions pour les MiniLM).
        model_max = getattr(self._model.tokenizer, "model_max_length", max_length) or max_length
        self._model.max_length = min(max_length, model_max)
        logger.info("Reranker %s chargé en %.1f s", model_name, time.perf_counter() - start)

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Score de pertinence entre 0 et 1 pour chaque passage."""
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages], batch_size=self.batch_size,
                                     show_progress_bar=False, activation_fn=None)
        return [1 / (1 + math.exp(-float(x))) for x in logits]
