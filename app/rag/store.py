"""Accès à la base vectorielle ChromaDB (mode persistant, ou en mémoire pour l'évaluation)."""

from pathlib import Path

COSINE = {"hnsw:space": "cosine"}


def persistent_client(path: Path):
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path),
                                     settings=ChromaSettings(anonymized_telemetry=False))


def ephemeral_client():
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False,
                                                            allow_reset=True))


def get_collection(client, name: str, metadata: dict | None = None):
    """Collection en similarité cosinus. Les embeddings sont toujours fournis par nous :
    Chroma ne charge aucun modèle."""
    return client.get_or_create_collection(name=name, metadata={**COSINE, **(metadata or {})},
                                           embedding_function=None)
