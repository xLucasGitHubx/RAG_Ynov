"""Évaluation de bout en bout des réponses sur le jeu Nexalis (eval/questions.jsonl).

Pour chaque question, l'assistant complet (recherche + reranking + LLM) répond, puis on vérifie :
- questions avec réponse : les mots-clés attendus (chiffres, termes) sont-ils dans la réponse ?
  le document attendu est-il cité dans les sources ? l'assistant a-t-il refusé à tort ?
- questions hors périmètre : l'assistant a-t-il bien répondu qu'il ne savait pas ?

Les résultats détaillés vont dans eval/results/, les métriques dans MLflow
(expérience « answers-nexalis »).

Usage :
    python -m eval.eval_answers                       # backend de LLM_PROVIDER (ollama en local)
    python -m eval.eval_answers --limit 10            # 10 premières questions
    python -m eval.eval_answers --ids tt-02 oos-01    # questions précises
"""

import argparse
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.llm import LLMError, build_llm_client
from app.prompts import PROMPT_VERSION
from app.rag.factory import build_retriever
from app.services.assistant import Assistant
from eval.common import MLFLOW_URI, RESULTS_DIR, read_jsonl
from eval.eval_retrieval import NEXALIS_QUESTIONS

logger = logging.getLogger("rag.eval.answers")


def keywords_ok(answer: str, patterns: list[str]) -> bool:
    """Chaque motif (expression régulière, alternatives séparées par |) doit apparaître.
    Les espaces insécables et fines sont normalisés (« 1 908 », « 9 h 30 »)."""
    text = re.sub(r"[  ]", " ", answer)
    return all(re.search(p, text, re.IGNORECASE) for p in patterns)


def evaluate_question(assistant: Assistant, q: dict) -> dict:
    start = time.perf_counter()
    try:
        result = assistant.answer(q["question"])
        error = None
    except LLMError as exc:
        result, error = None, str(exc)
    latency = (time.perf_counter() - start) * 1000

    row = {"id": q["id"], "type": q["type"], "question": q["question"],
           "expected": q.get("answer"), "latency_ms": round(latency), "error": error}
    if result is None:
        return row | {"correct": False}

    answer = result.response.answer
    documents = [s.document for s in result.response.sources]
    retrieved = [c.metadata.get("document") for c in result.chunks]
    row |= {
        "answer": answer,
        "refused": result.refused,
        "llm_called": result.llm_called,
        "sources": documents,
        "retrieved": retrieved,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "llm_meta": result.llm_meta,
        "timings_ms": {k: round(v) for k, v in result.timings_ms.items()},
    }
    if q["type"] == "hors_perimetre":
        row["correct"] = result.refused
    else:
        row["keywords_ok"] = keywords_ok(answer, q.get("keywords", []))
        row["source_cited"] = q["document"] in documents
        row["source_retrieved"] = q["document"] in retrieved
        row["correct"] = row["keywords_ok"] and not result.refused
    return row


def summarize(rows: list[dict]) -> dict[str, float]:
    answerable = [r for r in rows if r["type"] != "hors_perimetre"]
    oos = [r for r in rows if r["type"] == "hors_perimetre"]
    ratio = lambda items, key: sum(1 for r in items if r.get(key)) / len(items) if items else 0.0  # noqa: E731
    metrics = {
        "answer_accuracy": ratio(answerable, "correct"),
        "keywords_ok": ratio(answerable, "keywords_ok"),
        "source_cited": ratio(answerable, "source_cited"),
        "source_retrieved": ratio(answerable, "source_retrieved"),
        "false_refusal_rate": ratio(answerable, "refused"),
        "oos_refusal_rate": ratio(oos, "correct"),
        "error_rate": ratio(rows, "error"),
        "latency_ms_mean": sum(r["latency_ms"] for r in rows) / len(rows),
    }
    llm = [r["timings_ms"]["llm"] for r in rows if r.get("timings_ms", {}).get("llm")]
    if llm:
        metrics["llm_ms_mean"] = sum(llm) / len(llm)
    tokens = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
    if tokens:
        metrics["prompt_tokens_mean"] = sum(tokens) / len(tokens)
    by_type = defaultdict(list)
    for r in answerable:
        by_type[r["type"]].append(r)
    for kind, items in by_type.items():
        metrics[f"accuracy_{kind}"] = ratio(items, "correct")
    return metrics


def rescore(path: Path) -> None:
    """Recalcule « correct » à partir des réponses déjà générées, avec les mots-clés actuels de
    eval/questions.jsonl (utile quand un critère était trop strict) : aucun appel au LLM."""
    questions = {q["id"]: q for q in read_jsonl(NEXALIS_QUESTIONS)}
    rows = read_jsonl(path)
    for row in rows:
        q = questions[row["id"]]
        if row.get("answer") is None or q["type"] == "hors_perimetre":
            continue
        before = row["correct"]
        row["keywords_ok"] = keywords_ok(row["answer"], q.get("keywords", []))
        row["correct"] = row["keywords_ok"] and not row["refused"]
        if row["correct"] != before:
            print(f"  {row['id']} : {before} -> {row['correct']}")
    for key, value in summarize(rows).items():
        print(f"  {key:<28} {value:.3f}" if value <= 1 else f"  {key:<28} {value:.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--rescore", type=Path,
                        help="renote un fichier de résultats avec les critères actuels")
    args = parser.parse_args()
    logging.basicConfig(level="WARNING", format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    if args.rescore:
        rescore(args.rescore)
        return

    settings = get_settings()
    questions = read_jsonl(NEXALIS_QUESTIONS)
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids]
    if args.limit:
        questions = questions[: args.limit]

    llm = build_llm_client(settings)
    assistant = Assistant(llm, build_retriever(settings))
    rows = []
    for q in questions:
        row = evaluate_question(assistant, q)
        rows.append(row)
        status = "OK " if row["correct"] else "KO "
        print(f"{status} {row['id']:<7} {row['latency_ms']:>6} ms  "
              f"{(row.get('answer') or row.get('error') or '')[:110]!r}", flush=True)

    metrics = summarize(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = RESULTS_DIR / f"answers_{llm.name}_{PROMPT_VERSION}_{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{len(rows)} questions, résultats détaillés : {path}")
    for key, value in metrics.items():
        print(f"  {key:<28} {value:.3f}" if value <= 1 else f"  {key:<28} {value:.0f}")

    if not args.no_mlflow:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment("answers-nexalis")
        with mlflow.start_run(run_name=f"{llm.name}_{llm.model}_{stamp}"):
            mlflow.log_params({
                "llm_provider": llm.name, "llm_model": llm.model,
                "temperature": settings.llm_temperature, "n_questions": len(rows),
                "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
                "top_k": settings.retrieval_top_k, "fetch_k": settings.retrieval_fetch_k,
                "reranker": settings.reranker_model if settings.reranker_enabled else "aucun",
                "rerank_min_score": settings.rerank_min_score,
                "hybrid_search": settings.hybrid_search,
                "retrieval_min_score": settings.retrieval_min_score,
                "prompt_version": PROMPT_VERSION,
            })
            mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(path))


if __name__ == "__main__":
    main()
