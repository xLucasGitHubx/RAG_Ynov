"""Construction du retriever à partir de la configuration (index Chroma persistant)."""

from app.config import Settings
from app.rag.retriever import Retriever


class IndexNotReadyError(RuntimeError):
    """L'index Chroma est absent ou vide : l'ingestion n'a pas été lancée."""


def open_collection(settings: Settings):
    from app.rag.store import get_collection, persistent_client

    collection = get_collection(persistent_client(settings.chroma_dir), settings.chroma_collection)
    if collection.count() == 0:
        raise IndexNotReadyError(
            "L'index des documents est vide : lance « python -m ingestion.ingest »."
        )
    return collection


def build_retriever(settings: Settings) -> Retriever:
    from app.rag.embeddings import Embedder

    collection = open_collection(settings)
    reranker = None
    if settings.reranker_enabled:
        from app.rag.reranker import Reranker

        reranker = Reranker(settings.reranker_model)
    lexical = None
    if settings.hybrid_search:
        from app.rag.lexical import BM25Index

        lexical = BM25Index.from_collection(collection)
    return Retriever(
        collection,
        Embedder(settings.embedding_model, settings.embedding_max_length),
        reranker,
        fetch_k=settings.retrieval_fetch_k,
        top_k=settings.retrieval_top_k,
        min_rerank_score=settings.rerank_min_score,
        exclude_obsolete=settings.exclude_obsolete,
        lexical=lexical,
        lexical_weight=settings.hybrid_lexical_weight,
        min_score=settings.retrieval_min_score,
    )
