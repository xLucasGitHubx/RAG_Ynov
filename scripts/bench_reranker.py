"""Mesure la latence des rerankers sur CPU (20 passages réels de l'index par question).

Usage :
    python -m scripts.bench_reranker BAAI/bge-reranker-v2-m3 \
        cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
"""

import statistics
import sys
import time

from app.config import get_settings
from app.rag.embeddings import Embedder
from app.rag.factory import open_collection
from app.rag.reranker import Reranker

QUESTIONS = [
    "Combien de jours de télétravail par semaine ?",
    "Quel est le plafond pour une nuit d'hôtel à Paris ?",
    "Comment réinitialiser mon mot de passe ?",
    "Quel est le préavis de démission d'un cadre ?",
    "Combien de jours de congés pour un mariage ?",
]


def main(models: list[str]) -> None:
    settings = get_settings()
    collection = open_collection(settings)
    embedder = Embedder(settings.embedding_model, settings.embedding_max_length)
    candidates = []
    for q in QUESTIONS:
        res = collection.query(query_embeddings=[embedder.embed_query(q)], n_results=20,
                               include=["documents"])
        candidates.append((q, res["documents"][0]))

    for name in models:
        for max_length in (512, 1024):
            reranker = Reranker(name, max_length=max_length)
            reranker.score(*candidates[0])  # échauffement
            times = []
            for q, docs in candidates:
                start = time.perf_counter()
                reranker.score(q, docs)
                times.append(time.perf_counter() - start)
            print(f"{name:<50} max_len={max_length:<5} "
                  f"{statistics.mean(times):6.2f} s / question (20 passages)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or [get_settings().reranker_model])
