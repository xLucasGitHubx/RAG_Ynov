"""Routes d'administration de l'interface : ajout et retrait de documents (rôle admin).

L'ajout est synchrone : la requête répond une fois le document indexé (quelques secondes pour
du Markdown ou du Word, jusqu'à une minute pour un scan lu par OCR).
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from app.config import get_settings
from app.documents import DocumentError, add_document, delete_document
from app.rag.factory import IndexNotReadyError
from app.security.auth import Principal, require_admin

logger = logging.getLogger("rag.admin")

router = APIRouter(prefix="/api/admin", tags=["Administration"])

Admin = Annotated[Principal, Depends(require_admin)]


def _retriever():
    from app.main import get_retriever

    if not get_settings().rag_enabled:
        raise HTTPException(status_code=409, detail="La recherche est désactivée (RAG_ENABLED).")
    try:
        return get_retriever()
    except IndexNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/documents", status_code=201)
def upload_document(
    principal: Admin,
    fichier: UploadFile,
    titre: Annotated[str, Form(min_length=3, max_length=200)],
    categorie: Annotated[Literal["RH", "IT", "Autre"], Form()] = "RH",
    version: Annotated[str, Form(max_length=40)] = "",
    date_effet: Annotated[str, Form(pattern=r"^(\d{4}-\d{2}-\d{2})?$")] = "",
    statut: Annotated[Literal["en_vigueur", "obsolete"], Form()] = "en_vigueur",
    remplacer: Annotated[bool, Form()] = False,
) -> dict:
    """Ajoute un document au corpus (PDF, PDF scanné, Word, Markdown) et l'indexe aussitôt."""
    settings = get_settings()
    retriever = _retriever()
    content = fichier.file.read(settings.upload_max_mb * 1024 * 1024 + 1)
    fields = {"titre": titre, "categorie": categorie, "version": version,
              "date_effet": date_effet, "statut": statut}
    try:
        result = add_document(settings, retriever, fichier.filename or "", content, fields,
                              replace=remplacer)
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    logger.info("Document ajouté par %s : %s (%d chunks en %.1f s)", principal.key_id,
                result["document"], result["chunks"], result["seconds"])
    return result


@router.delete("/documents/{document}", status_code=204)
def remove_document(principal: Admin, document: str) -> None:
    """Retire un document ajouté depuis l'interface (le corpus de référence est protégé)."""
    try:
        delete_document(get_settings(), _retriever(), document)
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    logger.info("Document retiré par %s : %s", principal.key_id, document)
