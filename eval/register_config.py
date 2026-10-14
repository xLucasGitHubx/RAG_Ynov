"""Enregistre la configuration retenue du pipeline RAG dans le registre de modèles MLflow.

Le « modèle » enregistré est le pipeline complet (recherche hybride + prompt + LLM) sous forme
de modèle pyfunc : ses paramètres (découpage, recherche, seuil, LLM, version du prompt), ses
scores d'évaluation (tirés de app/reports/dashboard.json) et ses artefacts (prompt système,
configuration). Chaque exécution crée une nouvelle version de « assistant-rag-nexalis ».

Usage :
    python -m eval.register_config
    python -m eval.register_config --alias production
"""

import argparse
import json
import tempfile
from pathlib import Path

import mlflow

from app.config import get_settings
from app.dashboard import REPORT_FILE
from app.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from eval.common import MLFLOW_URI

MODEL_NAME = "assistant-rag-nexalis"
ROOT = Path(__file__).resolve().parents[1]


def evaluation_metrics() -> dict[str, float]:
    if not REPORT_FILE.exists():
        return {}
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    metrics = {}
    hybrid = next((c for c in report["retrieval"]["comparison"] if c["key"] == "hybrid"), None)
    if hybrid:
        metrics |= {f"nexalis_{k}": hybrid[k] for k in ("recall_at_1", "recall_at_5",
                                                        "recall_at_8", "mrr_at_10")}
    runs = report["answers"]["runs"]
    current = next((r for r in runs if r["version"] == PROMPT_VERSION), runs[-1] if runs else None)
    if current:
        s = current["summary"]
        metrics |= {"answer_accuracy": s["accuracy"], "false_refusals": s["false_refusals"],
                    "source_cited": s["source_cited"],
                    "oos_refusal_rate": s["oos_refused"] / max(s["oos_total"], 1)}
    security = report["security"]
    metrics |= {"pii_blocked_rate": security["blocked"] / max(len(security["messages"]), 1),
                "pii_false_positives": security["false_positives"]}
    if report.get("tests"):
        metrics["tests_passed"] = report["tests"]["passed"]
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--alias", default="candidate", help="alias de la version (ex. production)")
    args = parser.parse_args()

    settings = get_settings()
    params = {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.ollama_model if settings.llm_provider == "ollama"
        else settings.llm_space_id or settings.mistral_model,
        "llm_temperature": settings.llm_temperature,
        "prompt_version": PROMPT_VERSION,
        "embedding_model": settings.embedding_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunk_min_tokens": settings.chunk_min_tokens,
        "hybrid_search": settings.hybrid_search,
        "hybrid_lexical_weight": settings.hybrid_lexical_weight,
        "reranker": settings.reranker_model if settings.reranker_enabled else "aucun",
        "retrieval_fetch_k": settings.retrieval_fetch_k,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_score": settings.retrieval_min_score,
        "exclude_obsolete": settings.exclude_obsolete,
    }

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("configuration")
    with mlflow.start_run(run_name=f"config-{PROMPT_VERSION}") as run, \
            tempfile.TemporaryDirectory() as tmp:
        mlflow.log_params(params)
        mlflow.log_metrics(evaluation_metrics())
        prompt_file = Path(tmp) / "system_prompt.txt"
        prompt_file.write_text(SYSTEM_PROMPT, encoding="utf-8")
        config_file = Path(tmp) / "pipeline_config.json"
        config_file.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        mlflow.log_artifact(str(prompt_file))
        mlflow.log_artifact(str(config_file))
        info = mlflow.pyfunc.log_model(
            name="pipeline",
            python_model=str(Path(__file__).with_name("rag_pyfunc.py")),
            code_paths=[str(ROOT / "app")],
            registered_model_name=MODEL_NAME,
            pip_requirements=str(ROOT / "requirements.txt"),
            input_example=["Combien de jours de télétravail par semaine ?"],
        )
    client = mlflow.MlflowClient(MLFLOW_URI)
    version = info.registered_model_version
    client.set_registered_model_alias(MODEL_NAME, args.alias, version)
    client.update_model_version(MODEL_NAME, version, description=(
        f"Prompt {PROMPT_VERSION}, chunks {settings.chunk_size}/{settings.chunk_overlap}, "
        f"recherche {'hybride' if settings.hybrid_search else 'vectorielle'}, "
        f"seuil {settings.retrieval_min_score}, LLM {params['llm_model']}."
    ))
    print(f"Run {run.info.run_id} : {MODEL_NAME} version {version}, alias « {args.alias} »")


if __name__ == "__main__":
    main()
