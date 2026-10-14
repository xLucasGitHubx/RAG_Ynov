"""Point d'entrée de l'API FastAPI.

Lancement local : uvicorn app.main:app --reload --port 7860
Swagger         : http://localhost:7860/docs
"""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app import __version__
from app.config import Settings, get_settings
from app.dashboard import router as dashboard_router
from app.llm import LLMError, LLMNotConfiguredError, build_llm_client
from app.monitoring.tracker import (
    FeedbackRecord,
    RequestRecord,
    Tracker,
    build_tracker,
    new_request_id,
)
from app.prompts import PROMPT_VERSION
from app.rag.factory import IndexNotReadyError
from app.rag.retriever import RetrievedChunk
from app.schemas import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    IngestResponse,
)
from app.security import logging_filter
from app.security.auth import Principal, authenticate, require_admin
from app.security.pii import describe, detect_pii
from app.services.assistant import Assistant

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logging_filter.install()
logger = logging.getLogger("rag.api")


@lru_cache
def get_assistant() -> Assistant:
    current = get_settings()
    retriever = None
    if current.rag_enabled:
        from app.rag.factory import build_retriever

        retriever = build_retriever(current)
    return Assistant(build_llm_client(current), retriever)


@lru_cache
def get_tracker() -> Tracker:
    current = get_settings()
    return build_tracker(current.mlflow_tracking_enabled, current.mlflow_tracking_uri)


def track_request(
    request_id: str,
    endpoint: str,
    assistant: Assistant | None,
    question: str,
    *,
    answer: str = "",
    chunks: list[RetrievedChunk] | None = None,
    timings_ms: dict[str, float] | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    refused: bool = False,
    llm_called: bool = False,
    n_sources: int = 0,
    status: str = "ok",
) -> None:
    """Envoie au suivi MLflow les mesures d'une requête (jamais son contenu)."""
    current = get_settings()
    chunks = chunks or []
    scores = [c.relevance for c in chunks]
    metrics = {f"latency_{k}_ms": v for k, v in (timings_ms or {}).items()}
    metrics |= {
        "question_chars": len(question),
        "answer_chars": len(answer),
        "n_chunks": len(chunks),
        "n_sources": n_sources,
        "refused": int(refused),
        "llm_called": int(llm_called),
        "context_tokens": sum(c.metadata.get("n_tokens", 0) for c in chunks),
    }
    if scores:
        metrics |= {"top_score": max(scores), "mean_score": sum(scores) / len(scores)}
    if prompt_tokens is not None:
        metrics["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        metrics["completion_tokens"] = completion_tokens
    retriever = assistant.retriever if assistant else None
    reranker = getattr(retriever, "reranker", None)
    collection = getattr(retriever, "collection", None)
    params = {
        "llm_provider": assistant.llm.name if assistant else current.llm_provider,
        "llm_model": assistant.llm.model if assistant else "?",
        "embedding_model": current.embedding_model if retriever else "aucun",
        "reranker_model": getattr(reranker, "model_name", "aucun"),
        "index_signature": (getattr(collection, "metadata", None) or {}).get("signature", "?"),
        "top_k": current.retrieval_top_k,
        "prompt_version": PROMPT_VERSION,
    }
    get_tracker().track(RequestRecord(request_id, endpoint, params, metrics,
                                      {"status": status}))


def assistant_dependency() -> Assistant:
    try:
        return get_assistant()
    except (LLMNotConfiguredError, IndexNotReadyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not get_settings().api_keys:
        logger.warning("API_KEYS vide : authentification désactivée (à réserver au local).")
    # Chargement des modèles (embeddings, reranker) au démarrage plutôt qu'à la première question.
    if get_settings().rag_enabled:
        start = time.perf_counter()
        try:
            get_assistant()
            logger.info("Assistant prêt en %.1f s", time.perf_counter() - start)
        except Exception as exc:  # l'API démarre quand même : /health et /docs restent utiles
            logger.error("Assistant indisponible au démarrage : %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Assistant virtuel qui répond aux questions RH et IT des employés "
        "à partir des documents internes de l'entreprise (architecture RAG)."
    ),
    openapi_tags=[
        {"name": "Assistant", "description": "Poser une question à l'assistant."},
        {"name": "Supervision", "description": "État du service."},
        {"name": "Administration", "description": "Réservé au rôle admin."},
        {"name": "Interface", "description": "Données de l'interface web (/ui)."},
    ],
    lifespan=lifespan,
)


def check_question(question: str, request_id: str | None = None, endpoint: str = "") -> None:
    """Bloque les questions qui contiennent des données personnelles (RGPD) : elles ne sont ni
    envoyées au modèle ni journalisées. Seuls les types détectés sont tracés."""
    if not get_settings().pii_filter_enabled:
        return
    matches = detect_pii(question)
    if matches:
        kinds = describe(matches)
        logger.warning("Question bloquée : données personnelles détectées (%s)", kinds)
        if request_id:
            track_request(request_id, endpoint, None, question, status="bloquee_rgpd")
        raise HTTPException(
            status_code=400,
            detail=(
                f"Votre question contient des données personnelles ({kinds}). Pour les protéger, "
                "elle n'a pas été traitée : reformulez-la sans ces informations."
            ),
        )


def server_timing(timings_ms: dict[str, float]) -> str:
    """En-tête standard Server-Timing : durée de chaque étape, visible dans le navigateur."""
    return ", ".join(f"{name};dur={value:.0f}" for name, value in timings_ms.items())


UI_DIR = Path(__file__).parent / "static" / "ui"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """L'interface si elle est construite (cd frontend && npm run build), sinon le Swagger."""
    return RedirectResponse(url="/ui/" if (UI_DIR / "index.html").exists() else "/docs")


@app.get("/ui", include_in_schema=False)
@app.get("/ui/{path:path}", include_in_schema=False)
def ui(path: str = "") -> FileResponse:
    """Interface web (application monopage React) : fichier statique s'il existe, sinon
    index.html, pour que les adresses comme /ui/evaluation fonctionnent au rechargement."""
    if not (UI_DIR / "index.html").exists():
        raise HTTPException(status_code=404,
                            detail="Interface non construite : cd frontend && npm run build.")
    candidate = (UI_DIR / path).resolve()
    if path and candidate.is_file() and UI_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.include_router(dashboard_router)


@app.get("/health", response_model=HealthResponse, tags=["Supervision"])
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Vérifie que l'API répond (utilisé par Docker et, plus tard, par Azure)."""
    models = {"mistral": settings.mistral_model, "ollama": settings.ollama_model,
              "zerogpu": settings.llm_space_id or "?", "static": "static"}
    indexed = None
    if settings.rag_enabled and get_assistant.cache_info().currsize:
        retriever = get_assistant().retriever
        indexed = retriever.collection.count() if retriever else None
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        llm_model=models.get(settings.llm_provider, "?"),
        rag_enabled=settings.rag_enabled,
        indexed_chunks=indexed,
    )


@app.post("/ask", response_model=AskResponse, tags=["Assistant"])
def ask(
    payload: AskRequest,
    response: Response,
    principal: Annotated[Principal, Depends(authenticate)],
    assistant: Annotated[Assistant, Depends(assistant_dependency)],
) -> AskResponse:
    """Reçoit une question et renvoie la réponse de l'assistant avec ses sources."""
    request_id = new_request_id()
    response.headers["X-Request-ID"] = request_id
    check_question(payload.question, request_id, "ask")
    start = time.perf_counter()
    try:
        result = assistant.answer(payload.question)
    except LLMError as exc:
        logger.error("Génération impossible : %s", exc)
        track_request(request_id, "ask", assistant, payload.question, status="erreur_llm")
        raise HTTPException(
            status_code=502,
            detail="Le modèle de langage n'a pas pu répondre. Réessayez dans un instant.",
        ) from exc
    timings = {**result.timings_ms, "total": (time.perf_counter() - start) * 1000}
    response.headers["Server-Timing"] = server_timing(timings)
    # On ne journalise jamais le contenu de la question (précaution RGPD).
    logger.info(
        "Question traitée : %d caractères, %d sources, refus=%s, %s",
        len(payload.question),
        len(result.response.sources),
        result.refused,
        " ".join(f"{k}={v:.0f}ms" for k, v in timings.items()),
    )
    track_request(
        request_id, "ask", assistant, payload.question,
        answer=result.response.answer, chunks=result.chunks, timings_ms=timings,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        refused=result.refused, llm_called=result.llm_called,
        n_sources=len(result.response.sources),
    )
    result.response.request_id = request_id
    return result.response


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post(
    "/ask/stream",
    tags=["Assistant"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Flux SSE : événements sources, token, done (ou error)."}},
)
def ask_stream(
    payload: AskRequest,
    principal: Annotated[Principal, Depends(authenticate)],
    assistant: Annotated[Assistant, Depends(assistant_dependency)],
) -> StreamingResponse:
    """Même chose que /ask, mais la réponse arrive au fil de l'eau (Server-Sent Events).

    Événements : `sources` (extraits trouvés), `token` (morceau de texte, plusieurs fois),
    `done` (réponse complète, sources citées, durées) ou `error`."""
    request_id = new_request_id()
    check_question(payload.question, request_id, "ask_stream")

    def events() -> Iterator[str]:
        start = time.perf_counter()
        try:
            for kind, content in assistant.stream(payload.question):
                if kind == "sources":
                    yield _sse("sources", [s.model_dump() for s in content])
                elif kind == "token":
                    yield _sse("token", {"text": content})
                else:
                    chunks = content.pop("chunks", [])
                    stats = content.pop("stats", {})
                    content["timings_ms"]["total"] = (time.perf_counter() - start) * 1000
                    track_request(
                        request_id, "ask_stream", assistant, payload.question,
                        answer=content["answer"], chunks=chunks,
                        timings_ms=content["timings_ms"], n_sources=len(content["sources"]),
                        **stats,
                    )
                    content["sources"] = [s.model_dump() for s in content["sources"]]
                    content["request_id"] = request_id
                    yield _sse("done", content)
        except LLMError as exc:
            logger.error("Génération impossible (stream) : %s", exc)
            track_request(request_id, "ask_stream", assistant, payload.question,
                          status="erreur_llm")
            yield _sse("error", {"detail": "Le modèle de langage n'a pas pu répondre."})
        logger.info("Question traitée (stream) : %d caractères, %.0f ms",
                    len(payload.question), (time.perf_counter() - start) * 1000)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Request-ID": request_id})


@app.post("/feedback", response_model=FeedbackResponse, status_code=202, tags=["Assistant"])
def feedback(
    payload: FeedbackRequest,
    principal: Annotated[Principal, Depends(authenticate)],
) -> FeedbackResponse:
    """Pouce haut (1) ou bas (-1) sur une réponse, relié à la requête dans MLflow.
    Le commentaire n'est pas conservé (seule sa longueur), car il peut contenir des données
    personnelles."""
    get_tracker().feedback(FeedbackRecord(payload.request_id, payload.rating,
                                          len(payload.commentaire or "")))
    logger.info("Feedback %+d reçu", payload.rating)
    return FeedbackResponse()


@app.post("/ingest", response_model=IngestResponse, tags=["Administration"])
def ingest_documents(
    principal: Annotated[Principal, Depends(require_admin)],
    reset: bool = False,
) -> IngestResponse:
    """Réindexe les documents de data/raw (incrémental, ou complet avec reset=true), puis
    recharge l'assistant. Réservé au rôle admin."""
    from ingestion.ingest import ingest

    current = get_settings()
    if not current.rag_enabled:
        raise HTTPException(status_code=409, detail="La recherche est désactivée (RAG_ENABLED).")
    try:
        report = ingest(current, reset=reset)
    except ImportError as exc:  # dépendances d'ingestion absentes de l'image
        raise HTTPException(status_code=501, detail=f"Ingestion indisponible : {exc}") from exc
    get_assistant.cache_clear()
    logger.info("Réindexation par %s : %d ajouté(s), %d retiré(s)", principal.key_id,
                len(report.added), len(report.removed))
    return IngestResponse(added=report.added, skipped=report.skipped, removed=report.removed,
                          chunks=report.chunks, seconds=round(report.seconds, 1))
