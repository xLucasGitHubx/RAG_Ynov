"""Recherche des chunks pertinents : vecteurs (+ BM25), filtre de métadonnées, reranking."""

import logging
import time
from dataclasses import dataclass, field

from app.rag.lexical import BM25Index, reciprocal_rank_fusion

logger = logging.getLogger("rag.retriever")


@dataclass
class RetrievedChunk:
    id: str
    text: str
    metadata: dict
    score: float  # similarité cosinus (0 à 1)
    rerank_score: float | None = None

    @property
    def relevance(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.score


@dataclass
class SearchResult:
    chunks: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)
    candidates: int = 0  # nombre de chunks examinés avant reranking / filtrage


class Retriever:
    def __init__(
        self,
        collection,
        embedder,
        reranker=None,
        fetch_k: int = 20,
        top_k: int = 5,
        min_rerank_score: float = 0.0,
        exclude_obsolete: bool = True,
        lexical: BM25Index | None = None,
        lexical_weight: float = 1.0,
        min_score: float = 0.0,
    ) -> None:
        self.collection = collection
        self.embedder = embedder
        self.reranker = reranker
        self.fetch_k = fetch_k
        self.top_k = top_k
        self.min_rerank_score = min_rerank_score
        self.exclude_obsolete = exclude_obsolete
        self.lexical = lexical
        self.lexical_weight = lexical_weight
        # Si le meilleur chunk a une similarité cosinus inférieure, la question est jugée hors
        # périmètre : aucun extrait n'est renvoyé (l'assistant refuse sans appeler le LLM).
        self.min_score = min_score

    def refresh_lexical(self) -> None:
        """Reconstruit l'index BM25 après un ajout ou un retrait de document (l'index vectoriel,
        lui, est mis à jour directement dans Chroma)."""
        if self.lexical is not None:
            self.lexical = BM25Index.from_collection(self.collection)

    def search(self, question: str, top_k: int | None = None, where: dict | None = None,
               rerank: bool | None = None) -> SearchResult:
        top_k = top_k or self.top_k
        use_reranker = self.reranker is not None if rerank is None else rerank
        timings: dict[str, float] = {}

        start = time.perf_counter()
        vector = self.embedder.embed_query(question)
        timings["embedding"] = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        filters = dict(where or {})
        if self.exclude_obsolete:
            filters["statut"] = {"$ne": "obsolete"}
        n_results = max(self.fetch_k, top_k) if (use_reranker or self.lexical) else top_k
        n_results = min(n_results, max(self.collection.count(), 1))
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=n_results,
            where=_combine(filters),
            include=["documents", "metadatas", "distances"],
        )
        chunks = [
            RetrievedChunk(id=id_, text=doc, metadata=meta or {}, score=1 - dist)
            for id_, doc, meta, dist in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0],
                result["distances"][0], strict=True,
            )
        ]
        timings["vector_search"] = (time.perf_counter() - start) * 1000

        if self.lexical is not None and not where:
            start = time.perf_counter()
            chunks = self._hybrid(chunks, question, vector, n_results)
            timings["lexical_search"] = (time.perf_counter() - start) * 1000
        candidates = len(chunks)
        if chunks and max(c.score for c in chunks) < self.min_score:
            return SearchResult(chunks=[], timings_ms=timings, candidates=candidates)

        if use_reranker and chunks:
            start = time.perf_counter()
            scores = self.reranker.score(question, [c.text for c in chunks])
            for chunk, s in zip(chunks, scores, strict=True):
                chunk.rerank_score = s
            chunks.sort(key=lambda c: c.rerank_score, reverse=True)
            chunks = [c for c in chunks if c.rerank_score >= self.min_rerank_score]
            timings["rerank"] = (time.perf_counter() - start) * 1000

        return SearchResult(chunks=chunks[:top_k], timings_ms=timings, candidates=candidates)

    def _hybrid(self, dense: list[RetrievedChunk], question: str, vector: list[float],
                n: int) -> list[RetrievedChunk]:
        """Fusion RRF des classements vectoriel et BM25. Les chunks trouvés seulement par BM25
        reçoivent quand même leur similarité cosinus (calculée à partir de leur embedding)."""
        hits = self.lexical.search(question, n, exclude_obsolete=self.exclude_obsolete)
        by_id = {c.id: c for c in dense}
        missing = [h for h in hits if h.id not in by_id]
        if missing:
            stored = self.collection.get(ids=[h.id for h in missing], include=["embeddings"])
            for id_, emb in zip(stored["ids"], stored["embeddings"], strict=True):
                hit = next(h for h in missing if h.id == id_)
                cosine = float(sum(a * b for a, b in zip(vector, emb, strict=True)))
                by_id[id_] = RetrievedChunk(id_, hit.text, hit.metadata, cosine)
        order = reciprocal_rank_fusion([[c.id for c in dense], [h.id for h in hits]],
                                       weights=[1.0, self.lexical_weight])
        return [by_id[i] for i in order][:n]


def _combine(filters: dict) -> dict | None:
    """Chroma n'accepte qu'un opérateur par niveau : plusieurs conditions passent par $and."""
    if not filters:
        return None
    if len(filters) == 1:
        return filters
    return {"$and": [{k: v} for k, v in filters.items()]}
