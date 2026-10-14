"""Modèles Pydantic des requêtes et réponses de l'API."""

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Question posée par l'employé, en français.",
        examples=["Combien de jours de télétravail ai-je droit par semaine ?"],
    )


class Source(BaseModel):
    """Extrait de document utilisé pour construire la réponse."""

    document: str = Field(..., description="Nom du fichier source.")
    titre: str | None = Field(None, description="Titre du document.")
    section: str | None = Field(None, description="Chemin de section.")
    page: int | None = Field(None, description="Numéro de page, si le format en a.")
    score: float | None = Field(None, description="Score de pertinence (reranker ou cosinus).")
    extrait: str | None = Field(None, description="Début de l'extrait utilisé.")


class AskResponse(BaseModel):
    answer: str = Field(..., description="Réponse de l'assistant.")
    sources: list[Source] = Field(default_factory=list, description="Documents cités.")
    request_id: str | None = Field(None, description="Identifiant à renvoyer à /feedback.")


class FeedbackRequest(BaseModel):
    request_id: str = Field(..., pattern=r"^[0-9a-f]{32}$", description="Reçu dans /ask.")
    rating: Literal[1, -1] = Field(..., description="1 = pouce haut, -1 = pouce bas.")
    commentaire: str | None = Field(None, max_length=1000,
                                    description="Facultatif (seule sa longueur est conservée).")


class FeedbackResponse(BaseModel):
    status: str = Field("enregistré", examples=["enregistré"])


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    version: str = Field(..., examples=["0.1.0"])
    environment: str = Field(..., examples=["local"])
    llm_provider: str = Field(..., examples=["ollama"])
    llm_model: str = Field(..., examples=["ministral-3:3b"])
    rag_enabled: bool = Field(..., examples=[True])
    indexed_chunks: int | None = Field(None, description="Nombre de chunks dans l'index.")
    commit: str | None = Field(None, description="Commit déployé (GIT_SHA, posé par la CI).")


class IngestResponse(BaseModel):
    added: list[str] = Field(default_factory=list, description="Documents (ré)indexés.")
    skipped: list[str] = Field(default_factory=list, description="Documents inchangés.")
    removed: list[str] = Field(default_factory=list, description="Documents retirés.")
    chunks: int = Field(0, description="Nombre de chunks ajoutés.")
    seconds: float = Field(0, description="Durée de l'ingestion.")
