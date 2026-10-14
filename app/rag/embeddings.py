"""Modèle d'embeddings (BGE-M3 par défaut), exécuté sur CPU.

BGE-M3 n'a pas besoin de préfixe d'instruction : questions et passages sont encodés de la même
façon. Les vecteurs sont normalisés, la similarité cosinus revient donc au produit scalaire.
"""

import logging
import os
import time

logger = logging.getLogger("rag.embeddings")


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", max_length: int = 2048,
                 batch_size: int = 8, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer

        start = time.perf_counter()
        self.model_name = model_name
        self.batch_size = batch_size
        # Dans l'image Docker, les poids sont embarqués : aucun téléchargement au démarrage.
        # (HF_HUB_OFFLINE serait trop large : il bloquerait aussi l'appel au Space ZeroGPU.)
        local_only = os.environ.get("MODELS_LOCAL_ONLY") == "1"
        self._model = SentenceTransformer(model_name, device=device, local_files_only=local_only)
        self._model.max_seq_length = max_length
        # sentence-transformers 6 renomme la méthode ; on garde la compatibilité avec la v5.
        get_dimension = (getattr(self._model, "get_embedding_dimension", None)
                         or self._model.get_sentence_embedding_dimension)
        self.dimension = get_dimension()
        logger.info("Embeddings %s chargés en %.1f s", model_name, time.perf_counter() - start)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     show_progress_bar=len(texts) > 50, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
