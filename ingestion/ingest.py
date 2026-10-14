"""Pipeline d'ingestion : documents de data/raw -> Markdown -> chunks -> embeddings -> ChromaDB.

Idempotent : chaque fichier est identifié par son empreinte SHA-256. Seuls les fichiers nouveaux
ou modifiés sont réindexés ; les fichiers supprimés de data/raw sont retirés de l'index. Si la
configuration de découpage ou le modèle d'embeddings change, l'index est reconstruit.

Usage :
    python -m ingestion.ingest                 # indexation incrémentale
    python -m ingestion.ingest --reset         # reconstruction complète
    python -m ingestion.ingest --chunk-size 384 --overlap 38
"""

import argparse
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import ROOT_DIR, Settings, get_settings
from ingestion.chunking import Chunk, ChunkingConfig, bge_token_counter, chunk_markdown
from ingestion.parsing import SUPPORTED_SUFFIXES, TEXT_SUFFIXES, parse_file

logger = logging.getLogger("rag.ingestion")

PARSED_CACHE_DIR = ROOT_DIR / "data" / "parsed"
METADATA_FILE = "metadata.json"


@dataclass
class IngestReport:
    added: list[str]
    skipped: list[str]
    removed: list[str]
    chunks: int
    seconds: float


def file_hash(path: Path) -> str:
    """Empreinte du fichier. Pour le texte, les fins de ligne sont normalisées : un même document
    cloné sous Windows (CRLF) ou sous Linux, par la CI (LF), doit garder la même empreinte, sinon
    l'image Docker croirait tous les documents Markdown modifiés et les réindexerait."""
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_metadata(raw_dir: Path) -> dict[str, dict]:
    path = raw_dir / METADATA_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def list_documents(raw_dir: Path) -> list[Path]:
    return sorted(p for p in raw_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
                  and not p.name.startswith(".") and p.name != METADATA_FILE)


def parsed_markdown(path: Path, digest: str | None = None) -> str:
    """Markdown du document, avec un cache disque par empreinte : Docling n'est relancé que si le
    fichier a changé (utile pour l'évaluation, qui reconstruit l'index de nombreuses fois)."""
    digest = digest or file_hash(path)
    cache = PARSED_CACHE_DIR / f"{path.name}.{digest[:12]}.md"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    parsed = parse_file(path)
    PARSED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for old in PARSED_CACHE_DIR.glob(f"{path.name}.*.md"):
        old.unlink()
    cache.write_text(parsed.markdown, encoding="utf-8")
    return parsed.markdown


def chunk_document(path: Path, meta: dict, config: ChunkingConfig, count, digest: str | None = None
                   ) -> list[Chunk]:
    title = meta.get("titre") or path.stem.replace("_", " ")
    return chunk_markdown(parsed_markdown(path, digest), title, config, count)


def chunk_metadata(path: Path, meta: dict, chunk: Chunk, digest: str) -> dict:
    """Métadonnées stockées avec chaque chunk (Chroma n'accepte ni None ni listes)."""
    return {
        "document": path.name,
        "titre": meta.get("titre") or path.stem,
        "categorie": meta.get("categorie") or "",
        "version": str(meta.get("version") or ""),
        "date_effet": str(meta.get("date_effet") or ""),
        "statut": meta.get("statut") or "en_vigueur",
        "section": chunk.section,
        "sections": " | ".join(chunk.sections),
        "page": chunk.page if chunk.page is not None else -1,
        "chunk_index": chunk.index,
        "n_tokens": chunk.n_tokens,
        "file_hash": digest,
    }


def index_signature(settings: Settings, config: ChunkingConfig) -> str:
    return f"{settings.embedding_model}|{config.label}"


def ingest(settings: Settings | None = None, config: ChunkingConfig | None = None,
           reset: bool = False, collection=None, embedder=None,
           only: set[str] | None = None) -> IngestReport:
    """Indexe data/raw. Avec `only`, ne traite que ces fichiers et ne retire rien de l'index :
    c'est le cas de l'ajout d'un document depuis l'interface, qui ne doit jamais toucher au
    reste du corpus."""
    from app.rag.embeddings import Embedder
    from app.rag.store import get_collection, persistent_client

    settings = settings or get_settings()
    config = config or ChunkingConfig(settings.chunk_size, settings.chunk_overlap,
                                      settings.chunk_min_tokens)
    start = time.perf_counter()
    signature = index_signature(settings, config)

    if collection is None:
        client = persistent_client(settings.chroma_dir)
        existing = {c.name if hasattr(c, "name") else c for c in client.list_collections()}
        if settings.chroma_collection in existing:
            current = client.get_collection(settings.chroma_collection)
            if reset or (current.metadata or {}).get("signature") != signature:
                logger.info("Reconstruction complète de l'index (signature : %s)", signature)
                client.delete_collection(settings.chroma_collection)
        collection = get_collection(client, settings.chroma_collection,
                                    {"signature": signature})

    metadata = load_metadata(settings.raw_dir)
    documents = list_documents(settings.raw_dir)
    count = bge_token_counter(settings.embedding_model)
    report = IngestReport(added=[], skipped=[], removed=[], chunks=0, seconds=0)

    indexed = _indexed_hashes(collection)
    if only is not None:
        documents = [p for p in documents if p.name in only]
    else:
        for name in sorted(set(indexed) - {p.name for p in documents}):
            collection.delete(where={"document": name})
            report.removed.append(name)

    for path in documents:
        digest = file_hash(path)
        if indexed.get(path.name) == digest:
            report.skipped.append(path.name)
            continue
        meta = metadata.get(path.name, {})
        if not meta:
            logger.warning("%s : absent de %s, métadonnées par défaut", path.name, METADATA_FILE)
        chunks = chunk_document(path, meta, config, count, digest)
        if embedder is None:
            embedder = Embedder(settings.embedding_model, settings.embedding_max_length)
        vectors = embedder.embed_documents([c.text for c in chunks])
        collection.delete(where={"document": path.name})
        collection.add(
            ids=[f"{path.name}::{c.index}" for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[chunk_metadata(path, meta, c, digest) for c in chunks],
        )
        report.added.append(path.name)
        report.chunks += len(chunks)
        logger.info("%s : %d chunks indexés", path.name, len(chunks))

    report.seconds = time.perf_counter() - start
    return report


def _indexed_hashes(collection) -> dict[str, str]:
    """Empreinte de chaque document déjà indexé (lue dans les métadonnées des chunks)."""
    if collection.count() == 0:
        return {}
    metas = collection.get(include=["metadatas"])["metadatas"]
    return {m["document"]: m["file_hash"] for m in metas if m}


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexe les documents de data/raw dans ChromaDB.")
    parser.add_argument("--reset", action="store_true", help="reconstruit tout l'index")
    parser.add_argument("--chunk-size", type=int, help="taille des chunks en tokens (0 = section)")
    parser.add_argument("--overlap", type=int, help="chevauchement en tokens")
    parser.add_argument("--min-tokens", type=int, help="seuil de fusion des petits fragments")
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = get_settings()
    size = settings.chunk_size if args.chunk_size is None else (args.chunk_size or None)
    config = ChunkingConfig(
        chunk_size=size,
        chunk_overlap=settings.chunk_overlap if args.overlap is None else args.overlap,
        min_tokens=settings.chunk_min_tokens if args.min_tokens is None else args.min_tokens,
    )
    report = ingest(settings, config, reset=args.reset)
    print(f"Index : {settings.chroma_dir} (collection « {settings.chroma_collection} », "
          f"{config.label})")
    print(f"  {len(report.added)} document(s) indexé(s), {report.chunks} chunks")
    print(f"  {len(report.skipped)} inchangé(s), {len(report.removed)} retiré(s)")
    print(f"  durée : {report.seconds:.1f} s")


if __name__ == "__main__":
    main()
