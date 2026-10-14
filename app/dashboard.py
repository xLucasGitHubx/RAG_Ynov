"""Routes de l'interface : configuration, corpus, rapports d'évaluation, monitoring.

Toutes les routes sont en lecture seule, sous /api, et protégées par la même clé d'API que /ask.
Aucune ne renvoie de contenu de question (RGPD) : le monitoring ne lit que des métriques.
"""

import json
import logging
import statistics
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app import __version__
from app.config import ROOT_DIR, Settings, get_settings
from app.prompts import PROMPT_VERSION
from app.security.auth import authenticate

logger = logging.getLogger("rag.dashboard")

REPORT_FILE = ROOT_DIR / "app" / "reports" / "dashboard.json"
LATENCY_STAGES = ("embedding", "vector_search", "lexical_search", "rerank", "llm", "total")

router = APIRouter(prefix="/api", tags=["Interface"],
                   dependencies=[Depends(authenticate)])

CurrentSettings = Annotated[Settings, Depends(get_settings)]


# --------------------------------------------------------------------------- configuration


@router.get("/config")
def config(settings: CurrentSettings) -> dict[str, Any]:
    """Configuration effective du pipeline (aucun secret)."""
    models = {"mistral": settings.mistral_model, "ollama": settings.ollama_model,
              "zerogpu": settings.llm_space_id or "?", "static": "static"}
    return {
        "version": __version__,
        "environment": settings.environment,
        "prompt_version": PROMPT_VERSION,
        "llm": {
            "provider": settings.llm_provider,
            "model": models.get(settings.llm_provider, "?"),
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "context": settings.ollama_num_ctx if settings.llm_provider == "ollama" else None,
        },
        "retrieval": {
            "enabled": settings.rag_enabled,
            "embedding_model": settings.embedding_model,
            "hybrid_search": settings.hybrid_search,
            "lexical_weight": settings.hybrid_lexical_weight,
            "reranker": settings.reranker_model if settings.reranker_enabled else None,
            "fetch_k": settings.retrieval_fetch_k,
            "top_k": settings.retrieval_top_k,
            "min_score": settings.retrieval_min_score,
            "exclude_obsolete": settings.exclude_obsolete,
        },
        "chunking": {
            "size": settings.chunk_size,
            "overlap": settings.chunk_overlap,
            "min_tokens": settings.chunk_min_tokens,
        },
        "security": {
            "auth_enabled": bool(settings.api_keys and settings.api_keys.get_secret_value()),
            "rate_limit_per_minute": settings.rate_limit_per_minute,
            "pii_filter": settings.pii_filter_enabled,
        },
        "tracking": {"mlflow": settings.mlflow_tracking_enabled},
    }


# --------------------------------------------------------------------------- corpus


def _collection():
    """Collection Chroma de l'assistant déjà chargé (None si la recherche est désactivée)."""
    from app.main import get_assistant

    if not get_settings().rag_enabled:
        return None
    retriever = get_assistant().retriever
    return getattr(retriever, "collection", None)


def _metadata(settings: Settings) -> dict[str, dict]:
    path = settings.raw_dir / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@router.get("/documents")
def documents(settings: CurrentSettings) -> list[dict[str, Any]]:
    """Documents du corpus, avec leurs métadonnées et leurs statistiques d'indexation."""
    stats: dict[str, dict] = {}
    collection = _collection()
    if collection is not None:
        for meta in collection.get(include=["metadatas"])["metadatas"]:
            entry = stats.setdefault(meta["document"], {"chunks": 0, "tokens": 0, "pages": 0})
            entry["chunks"] += 1
            entry["tokens"] += int(meta.get("n_tokens", 0))
            entry["pages"] = max(entry["pages"], int(meta.get("page", -1)))
    rows = []
    for name, meta in sorted(_metadata(settings).items()):
        indexed = stats.get(name, {})
        rows.append({
            "document": name,
            "titre": meta.get("titre"),
            "format": meta.get("format"),
            "categorie": meta.get("categorie"),
            "version": meta.get("version"),
            "date_effet": meta.get("date_effet"),
            "statut": meta.get("statut"),
            "sources": " ".join(str(meta.get("sources", "")).split()),
            "chunks": indexed.get("chunks"),
            "tokens": indexed.get("tokens"),
            "pages": indexed.get("pages") or None,
        })
    return rows


@router.get("/documents/{document}/chunks")
def document_chunks(document: str) -> list[dict[str, Any]]:
    """Chunks indexés d'un document, dans l'ordre : pour montrer le découpage."""
    collection = _collection()
    if collection is None:
        raise HTTPException(status_code=409, detail="La recherche est désactivée (RAG_ENABLED).")
    data = collection.get(where={"document": document}, include=["documents", "metadatas"])
    if not data["ids"]:
        raise HTTPException(status_code=404, detail=f"Document inconnu : {document}")
    chunks = [
        {
            "index": int(meta.get("chunk_index", 0)),
            "section": meta.get("section"),
            "page": meta.get("page") if int(meta.get("page", -1)) > 0 else None,
            "tokens": int(meta.get("n_tokens", 0)),
            "text": text.split("\n\n", 1)[-1],
        }
        for text, meta in zip(data["documents"], data["metadatas"], strict=True)
    ]
    return sorted(chunks, key=lambda c: c["index"])


# --------------------------------------------------------------------------- rapports


@lru_cache(maxsize=1)
def _report(mtime: float) -> dict:
    return json.loads(REPORT_FILE.read_text(encoding="utf-8"))


@router.get("/reports")
def reports() -> dict:
    """Résultats d'évaluation consolidés (généré par `python -m scripts.export_reports`)."""
    if not REPORT_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Rapport absent : lancez « python -m scripts.export_reports ».",
        )
    return _report(REPORT_FILE.stat().st_mtime)


# --------------------------------------------------------------------------- monitoring


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def summarize_runs(runs: list[dict]) -> dict[str, Any]:
    """Agrège les runs MLflow de l'expérience « requests » (une entrée par question)."""
    statuses: dict[str, int] = {}
    for run in runs:
        statuses[run["status"]] = statuses.get(run["status"], 0) + 1
    answered = [r for r in runs if r["status"] == "ok"]
    latency = {}
    for stage in LATENCY_STAGES:
        values = [r["metrics"][f"latency_{stage}_ms"] for r in answered
                  if f"latency_{stage}_ms" in r["metrics"]]
        if values:
            latency[stage] = {
                "p50": _percentile(values, 0.5),
                "p95": _percentile(values, 0.95),
                "mean": statistics.fmean(values),
                "count": len(values),
            }
    ratings = [r["feedback"] for r in runs if r["feedback"] is not None]

    def rate(key: str) -> float | None:
        values = [r["metrics"].get(key) for r in answered if key in r["metrics"]]
        return statistics.fmean(values) if values else None

    return {
        "available": True,
        "total": len(runs),
        "statuses": statuses,
        "refusal_rate": rate("refused"),
        "llm_call_rate": rate("llm_called"),
        "mean_top_score": rate("top_score"),
        "mean_prompt_tokens": rate("prompt_tokens"),
        "feedback": {"positive": sum(1 for x in ratings if x > 0),
                     "negative": sum(1 for x in ratings if x < 0)},
        "latency": latency,
        "recent": [
            {
                "request_id": r["request_id"][:8],
                "time": r["time"],
                "endpoint": r["endpoint"],
                "status": r["status"],
                "refused": bool(r["metrics"].get("refused")),
                "llm_called": bool(r["metrics"].get("llm_called")),
                "total_ms": r["metrics"].get("latency_total_ms"),
                "llm_ms": r["metrics"].get("latency_llm_ms"),
                "n_sources": r["metrics"].get("n_sources"),
                "top_score": r["metrics"].get("top_score"),
                "feedback": r["feedback"],
            }
            for r in runs[:50]
        ],
    }


@router.get("/monitoring")
def monitoring(settings: CurrentSettings,
               limit: Annotated[int, Query(ge=1, le=2000)] = 500) -> dict[str, Any]:
    """Synthèse des dernières questions posées à l'API (lue dans MLflow)."""
    if not settings.mlflow_tracking_enabled:
        return {"available": False, "reason": "Suivi MLflow désactivé (MLFLOW_TRACKING_ENABLED)."}
    try:
        from mlflow import MlflowClient
    except ImportError:
        return {"available": False, "reason": "MLflow n'est pas installé dans cet environnement."}
    client = MlflowClient(settings.mlflow_tracking_uri)
    experiment = client.get_experiment_by_name("requests")
    if experiment is None:
        return {"available": True, "total": 0, "statuses": {}, "latency": {}, "recent": [],
                "feedback": {"positive": 0, "negative": 0}}
    found = client.search_runs([experiment.experiment_id], max_results=limit,
                               order_by=["attributes.start_time DESC"])
    runs = [
        {
            "request_id": run.data.tags.get("request_id", run.info.run_id),
            "time": run.info.start_time,
            "endpoint": run.data.tags.get("endpoint", "?"),
            "status": run.data.tags.get("status", "ok"),
            "metrics": run.data.metrics,
            "feedback": run.data.metrics.get("feedback"),
        }
        for run in found
    ]
    return summarize_runs(runs)
