"""Ajout et retrait de documents depuis l'interface (rôle admin).

Le fichier est enregistré dans data/raw, ses métadonnées dans data/raw/metadata.json, puis
l'ingestion incrémentale l'indexe (Docling pour le PDF, le scan avec OCR et Word ; Markdown lu
tel quel) avec la collection Chroma et le modèle d'embeddings déjà chargés par l'API : pas de
second BGE-M3 en mémoire. L'index BM25 est ensuite reconstruit.

Seuls les documents ajoutés de cette façon peuvent être retirés : le corpus de référence, celui
de l'évaluation, reste intact.

En production (Azure Container Apps), le disque du conteneur est éphémère : un ajout disparaît
au redéploiement. Pour l'intégrer durablement, le placer dans data/raw du dépôt et réindexer.
"""

import gc
import importlib.util
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from app.config import Settings

logger = logging.getLogger("rag.documents")

# Extension -> valeur du champ « format » de metadata.json (pdf_scan est détecté à l'ajout).
UPLOAD_SUFFIXES = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".markdown": "md", ".txt": "md"}
ORIGIN = "interface"
METADATA_FILE = "metadata.json"
# Moins de caractères que cela par page dans la couche texte : le PDF est un scan (OCR nécessaire).
SCAN_CHARS_PER_PAGE = 50

_lock = threading.Lock()


class DocumentError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


def safe_filename(filename: str) -> str:
    """Nom de fichier sûr : sans chemin, sans accents ni espaces, extension autorisée."""
    base = Path(filename.replace("\\", "/")).name
    stem, _, suffix = base.rpartition(".")
    suffix = f".{suffix.lower()}" if stem else ""
    if suffix not in UPLOAD_SUFFIXES:
        raise DocumentError(415, f"Format non pris en charge ({suffix or 'sans extension'}) : "
                                 "PDF (y compris scanné), Word (.docx) ou Markdown (.md).")
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    clean = re.sub(r"[^A-Za-z0-9]+", "_", ascii_stem).strip("_").lower()[:80]
    if not clean:
        raise DocumentError(400, "Nom de fichier invalide.")
    return clean + suffix


def is_scanned_pdf(path: Path) -> bool:
    """Vrai si le PDF n'a presque pas de couche texte (document scanné)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return False
    try:
        pdf = pdfium.PdfDocument(path)
        pages = len(pdf)
        chars = sum(len(pdf[i].get_textpage().get_text_range().strip()) for i in range(pages))
        pdf.close()
    except Exception:  # PDF illisible : Docling tranchera
        return False
    return pages > 0 and chars / pages < SCAN_CHARS_PER_PAGE


def load_metadata(raw_dir: Path) -> dict[str, dict]:
    path = raw_dir / METADATA_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_metadata(raw_dir: Path, metadata: dict[str, dict]) -> None:
    path = raw_dir / METADATA_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _run_ingest(settings: Settings, retriever, name: str):
    from ingestion.ingest import ingest
    from ingestion.parsing import _converter

    try:
        return ingest(settings, collection=retriever.collection, embedder=retriever.embedder,
                      only={name})
    finally:
        # Les modèles de Docling (mise en page, tableaux, OCR) occupent près d'1 Go : on les libère
        # après chaque ajout, l'application n'a que 4 Go et BGE-M3 en occupe déjà la moitié.
        _converter.cache_clear()
        gc.collect()
        _release_memory()


def _release_memory() -> None:
    """Rend au système la mémoire libérée (sinon glibc la garde et chaque ajout fait grimper la
    consommation du conteneur). Sans effet hors Linux."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def add_document(settings: Settings, retriever, filename: str, content: bytes, fields: dict,
                 replace: bool = False, ingest_fn=None) -> dict:
    """Enregistre puis indexe un document. Annule tout (fichier, métadonnées) en cas d'échec."""
    name = safe_filename(filename)
    if not content:
        raise DocumentError(400, "Le fichier est vide.")
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise DocumentError(413, f"Fichier trop volumineux (maximum {settings.upload_max_mb} Mo).")
    if Path(name).suffix in {".pdf", ".docx"} and not docling_available():
        raise DocumentError(501, "Docling n'est pas installé : seul le Markdown peut être ajouté.")
    if not _lock.acquire(blocking=False):
        raise DocumentError(409, "Une indexation est déjà en cours : réessayez dans un instant.")
    try:
        raw_dir = settings.raw_dir
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / name
        metadata = load_metadata(raw_dir)
        existing = metadata.get(name)
        if existing is not None and existing.get("origine") != ORIGIN:
            raise DocumentError(409, f"« {name} » fait partie du corpus de référence : "
                                     "renommez le fichier.")
        if (existing is not None or path.exists()) and not replace:
            raise DocumentError(409, f"Un document « {name} » existe déjà : cochez « Remplacer ».")

        previous_file = path.read_bytes() if path.exists() else None
        previous_meta = dict(metadata)
        path.write_bytes(content)
        doc_format = UPLOAD_SUFFIXES[path.suffix]
        if doc_format == "pdf" and is_scanned_pdf(path):
            doc_format = "pdf_scan"
        now = datetime.now()
        metadata[name] = {
            "titre": fields["titre"].strip(),
            "format": doc_format,
            "categorie": fields.get("categorie") or "Autre",
            "version": (fields.get("version") or "").strip() or None,
            "date_effet": fields.get("date_effet") or None,
            "statut": fields.get("statut") or "en_vigueur",
            "sources": f"Ajouté depuis l'interface le {now:%d/%m/%Y à %H:%M}.",
            "origine": ORIGIN,
            "ajoute_le": now.isoformat(timespec="seconds"),
        }
        save_metadata(raw_dir, metadata)

        try:
            report = (ingest_fn or _run_ingest)(settings, retriever, name)
            chunks = len(retriever.collection.get(where={"document": name}, include=[])["ids"])
            if chunks == 0:
                raise ValueError("aucun texte n'a pu être extrait du document")
        except Exception as exc:
            if previous_file is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous_file)
            save_metadata(raw_dir, previous_meta)
            # Le document peut avoir été partiellement indexé : on retire ses chunks.
            retriever.collection.delete(where={"document": name})
            if previous_file is not None:
                (ingest_fn or _run_ingest)(settings, retriever, name)
            retriever.refresh_lexical()
            logger.warning("Ajout de %s annulé : %s", name, exc)
            raise DocumentError(422, f"Indexation impossible : {exc}") from exc

        retriever.refresh_lexical()
        return {"document": name, "format": doc_format, "chunks": chunks,
                "seconds": round(report.seconds, 1)}
    finally:
        _lock.release()


def delete_document(settings: Settings, retriever, name: str) -> None:
    """Retire un document ajouté depuis l'interface (fichier, métadonnées et chunks)."""
    if Path(name).name != name:
        raise DocumentError(400, "Nom de document invalide.")
    metadata = load_metadata(settings.raw_dir)
    entry = metadata.get(name)
    if entry is None:
        raise DocumentError(404, f"Document inconnu : {name}")
    if entry.get("origine") != ORIGIN:
        raise DocumentError(403, "Seuls les documents ajoutés depuis l'interface peuvent être "
                                 "retirés : le corpus de référence est celui de l'évaluation.")
    if not _lock.acquire(blocking=False):
        raise DocumentError(409, "Une indexation est en cours : réessayez dans un instant.")
    try:
        from ingestion.ingest import PARSED_CACHE_DIR

        (settings.raw_dir / name).unlink(missing_ok=True)
        del metadata[name]
        save_metadata(settings.raw_dir, metadata)
        retriever.collection.delete(where={"document": name})
        for cache in PARSED_CACHE_DIR.glob(f"{name}.*.md"):
            cache.unlink(missing_ok=True)
        retriever.refresh_lexical()
    finally:
        _lock.release()
