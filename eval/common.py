"""Outils partagés par les scripts d'évaluation : métriques, cache d'embeddings, index éphémère."""

import hashlib
import json
import pickle
import re
import unicodedata
from pathlib import Path

from app.config import ROOT_DIR

EVAL_DIR = ROOT_DIR / "eval"
CACHE_DIR = EVAL_DIR / ".cache"
RESULTS_DIR = EVAL_DIR / "results"
MLFLOW_URI = f"sqlite:///{(ROOT_DIR / 'mlflow.db').as_posix()}"


# --------------------------------------------------------------------------- métriques


def first_hit_rank(hits: list[bool]) -> int | None:
    """Rang (1 = premier) du premier résultat pertinent, None si absent."""
    return next((i + 1 for i, hit in enumerate(hits) if hit), None)


def recall_at_k(ranks: list[int | None], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr_at_k(ranks: list[int | None], k: int = 10) -> float:
    return sum(1 / r for r in ranks if r is not None and r <= k) / len(ranks)


# --------------------------------------------------------------------------- normalisation


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : pour comparer des titres d'articles."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --------------------------------------------------------------------------- embeddings


class CachedEmbedder:
    """Enveloppe un Embedder avec un cache disque : la grille de chunking ré-encode souvent les
    mêmes textes (mêmes sections, mêmes questions)."""

    def __init__(self, embedder) -> None:
        self.embedder = embedder
        self.model_name = embedder.model_name
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = CACHE_DIR / f"embeddings_{normalize(self.model_name).replace(' ', '_')}.pkl"
        self.cache: dict[str, list[float]] = (
            pickle.loads(self.path.read_bytes()) if self.path.exists() else {}
        )
        self.dirty = False

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if self._key(t) not in self.cache))
        if missing:
            for text, vector in zip(missing, self.embedder.embed_documents(missing), strict=True):
                self.cache[self._key(text)] = vector
            self.dirty = True
        return [self.cache[self._key(t)] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def save(self) -> None:
        if self.dirty:
            self.path.write_bytes(pickle.dumps(self.cache))
            self.dirty = False


def build_ephemeral_collection(name: str, chunks_with_meta: list[tuple[str, str, dict]], embedder):
    """Index Chroma en mémoire : (id, texte, métadonnées) -> collection prête à interroger."""
    from app.rag.store import ephemeral_client, get_collection

    client = ephemeral_client()
    try:
        client.delete_collection(name)
    except Exception:  # la collection n'existe pas encore
        pass
    collection = get_collection(client, name)
    ids, texts, metas = zip(*chunks_with_meta, strict=True)
    vectors = embedder.embed_documents(list(texts))
    for start in range(0, len(ids), 1000):
        collection.add(ids=list(ids[start:start + 1000]),
                       documents=list(texts[start:start + 1000]),
                       embeddings=vectors[start:start + 1000],
                       metadatas=list(metas[start:start + 1000]))
    return collection
