"""Évaluation du retrieval et choix de la taille de chunk.

Pour chaque configuration de découpage (taille, overlap, fusion, reranker), on reconstruit un
index Chroma en mémoire, on pose les questions annotées et on mesure :
- recall@k : la bonne source est-elle dans les k premiers chunks ?
- MRR@10   : à quel rang arrive-t-elle (1/rang, moyenné) ?
- ctx@5    : nombre moyen de tokens envoyés au LLM avec les 5 premiers chunks.

Jeux de questions :
- syntec  : 100 questions MTEB-French (lyon-nlp), chacune reliée à un article de la convention ;
- nexalis : questions maison (eval/questions.jsonl), reliées à un document et une section.

Chaque configuration est un run MLflow (expérience « retrieval-chunking »).

Usage :
    python -m eval.eval_retrieval --dataset syntec --grid full
    python -m eval.eval_retrieval --dataset syntec --grid quick --reranker
    python -m eval.eval_retrieval --dataset nexalis --sizes 384 512 --overlaps 0.1
"""

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.rag.lexical import BM25Index
from app.rag.retriever import Retriever
from eval.common import (
    MLFLOW_URI,
    RESULTS_DIR,
    CachedEmbedder,
    build_ephemeral_collection,
    first_hit_rank,
    mrr_at_k,
    normalize,
    read_jsonl,
    recall_at_k,
)
from ingestion.chunking import ChunkingConfig, bge_token_counter
from ingestion.ingest import (
    chunk_document,
    chunk_metadata,
    file_hash,
    list_documents,
    load_metadata,
)

logger = logging.getLogger("rag.eval")

SYNTEC_DIR = Path(__file__).parent / "syntec"
NEXALIS_QUESTIONS = Path(__file__).parent / "questions.jsonl"
SYNTEC_FILE = "convention_collective_syntec.md"
KS = (1, 3, 5, 8, 10)

GRIDS = {
    "full": {"sizes": [256, 384, 512, 768, 1024, 0], "overlaps": [0.0, 0.1, 0.2]},
    "quick": {"sizes": [256, 384, 512, 768, 0], "overlaps": [0.1]},
}


@dataclass
class Query:
    question: str
    is_hit: callable  # métadonnées d'un chunk -> bool


# --------------------------------------------------------------------------- jeux de questions


def syntec_queries() -> list[Query]:
    articles = json.loads((SYNTEC_DIR / "articles.json").read_text(encoding="utf-8"))
    titles = {a["id"]: normalize(a["title"]) for a in articles}

    def hit_for(article_id: str):
        target = titles[article_id]
        return lambda meta: any(normalize(s.rsplit(" > ", 1)[-1]) == target
                                for s in meta["sections"].split(" | "))

    return [Query(q["question"], hit_for(q["article"]))
            for q in read_jsonl(SYNTEC_DIR / "queries.jsonl")]


def nexalis_queries() -> list[Query]:
    """Questions maison avec une source attendue (les questions hors périmètre sont ignorées)."""
    queries = []
    for q in read_jsonl(NEXALIS_QUESTIONS):
        if not q.get("document"):
            continue
        doc, section = q["document"], normalize(q.get("section") or "")

        def is_hit(meta, doc=doc, section=section):
            return meta["document"] == doc and section in normalize(meta["sections"])

        queries.append(Query(q["question"], is_hit))
    return queries


# --------------------------------------------------------------------------- évaluation


def build_index(dataset: str, config: ChunkingConfig, embedder, count):
    settings = get_settings()
    metadata = load_metadata(settings.raw_dir)
    paths = list_documents(settings.raw_dir)
    if dataset == "syntec":
        paths = [p for p in paths if p.name == SYNTEC_FILE]
    rows = []
    for path in paths:
        digest = file_hash(path)
        meta = metadata.get(path.name, {})
        for chunk in chunk_document(path, meta, config, count, digest):
            rows.append((f"{path.name}::{chunk.index}", chunk.text,
                         chunk_metadata(path, meta, chunk, digest)))
    collection = build_ephemeral_collection(f"eval_{dataset}", rows, embedder)
    return collection, [r[2]["n_tokens"] for r in rows]


def evaluate(queries: list[Query], retriever: Retriever, rerank: bool) -> dict:
    ranks, ctx_tokens, latencies = [], [], []
    for query in queries:
        start = time.perf_counter()
        result = retriever.search(query.question, top_k=max(KS), rerank=rerank)
        latencies.append((time.perf_counter() - start) * 1000)
        ranks.append(first_hit_rank([query.is_hit(c.metadata) for c in result.chunks]))
        ctx_tokens.append(sum(c.metadata["n_tokens"] for c in result.chunks[:5]))
    metrics = {f"recall_at_{k}": recall_at_k(ranks, k) for k in KS}
    metrics["mrr_at_10"] = mrr_at_k(ranks, 10)
    metrics["ctx_tokens_at_5"] = sum(ctx_tokens) / len(ctx_tokens)
    metrics["latency_ms"] = sum(latencies) / len(latencies)
    return metrics


def run(dataset: str, sizes: list[int], overlaps: list[float], min_tokens: list[int],
        rerank_modes: list[bool], log_mlflow: bool = True,
        hybrid_modes: tuple[bool, ...] = (False,)) -> list[dict]:
    from app.rag.embeddings import Embedder

    settings = get_settings()
    count = bge_token_counter(settings.embedding_model)
    embedder = CachedEmbedder(Embedder(settings.embedding_model, settings.embedding_max_length))
    reranker = None
    if any(rerank_modes):
        from app.rag.reranker import Reranker

        reranker = Reranker(settings.reranker_model)
    queries = syntec_queries() if dataset == "syntec" else nexalis_queries()
    logger.info("%d questions (%s)", len(queries), dataset)

    if log_mlflow:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment("retrieval-chunking")

    results = []
    for size in sizes:
        # « 0 » = par section, sans redécoupage : l'overlap n'a pas de sens.
        for overlap in ([0.0] if size == 0 else overlaps):
            for min_tok in min_tokens:
                config = ChunkingConfig(chunk_size=size or None,
                                        chunk_overlap=int(size * overlap), min_tokens=min_tok)
                start = time.perf_counter()
                collection, chunk_tokens = build_index(dataset, config, embedder, count)
                build_s = time.perf_counter() - start
                embedder.save()
                lexical = BM25Index.from_collection(collection) if any(hybrid_modes) else None
                for hybrid, rerank in [(h, r) for h in hybrid_modes for r in rerank_modes]:
                    retriever = Retriever(collection, embedder, reranker,
                                          fetch_k=settings.retrieval_fetch_k, top_k=max(KS),
                                          exclude_obsolete=settings.exclude_obsolete,
                                          lexical=lexical if hybrid else None,
                                          lexical_weight=settings.hybrid_lexical_weight)
                    metrics = evaluate(queries, retriever, rerank)
                    row = {
                        "dataset": dataset,
                        "chunk_size": size or "section",
                        "overlap": overlap,
                        "min_tokens": min_tok,
                        "hybrid": settings.hybrid_lexical_weight if hybrid else False,
                        "reranker": settings.reranker_model.split("/")[-1] if rerank else False,
                        "n_chunks": len(chunk_tokens),
                        "avg_chunk_tokens": round(sum(chunk_tokens) / len(chunk_tokens), 1),
                        "index_build_s": round(build_s, 1),
                        **{k: round(v, 4) for k, v in metrics.items()},
                    }
                    results.append(row)
                    print(_format_row(row), flush=True)
                    if log_mlflow:
                        _log_mlflow(row, config, settings)
    embedder.save()
    return results


def _log_mlflow(row: dict, config: ChunkingConfig, settings) -> None:
    import mlflow

    name = f"{row['dataset']}_{config.label}_hybrid={row['hybrid']}_rerank={row['reranker']}"
    with mlflow.start_run(run_name=name):
        mlflow.log_params({
            "dataset": row["dataset"], "chunk_size": row["chunk_size"],
            "chunk_overlap_tokens": config.chunk_overlap, "overlap_ratio": row["overlap"],
            "min_tokens": row["min_tokens"], "reranker": row["reranker"],
            "hybrid": row["hybrid"],
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.reranker_model if row["reranker"] else "aucun",
            "fetch_k": settings.retrieval_fetch_k,
        })
        mlflow.log_metrics({k: float(v) for k, v in row.items()
                            if k.startswith(("recall", "mrr", "ctx", "latency", "n_chunks",
                                             "avg_chunk", "index_build"))})


def _format_row(row: dict) -> str:
    return (f"size={row['chunk_size']!s:>7} overlap={row['overlap']:.0%} "
            f"min={row['min_tokens']:>3} "
            f"hybrid={row['hybrid']!s:5} rerank={row['reranker']!s:5} chunks={row['n_chunks']:>4} "
            f"R@1={row['recall_at_1']:.2f} R@3={row['recall_at_3']:.2f} "
            f"R@5={row['recall_at_5']:.2f} R@8={row['recall_at_8']:.2f} "
            f"MRR={row['mrr_at_10']:.3f} ctx@5={row['ctx_tokens_at_5']:.0f} "
            f"lat={row['latency_ms']:.0f}ms")


def decide(results: list[dict], tolerance: float = 0.02) -> dict:
    """Règle du plan : la plus petite taille dont le recall@5 est à moins de 2 points du meilleur
    (à reranking égal, on garde la configuration qui envoie le moins de tokens)."""
    best = max(r["recall_at_5"] for r in results)
    eligible = [r for r in results if r["recall_at_5"] >= best - tolerance]
    # Une configuration lente (> 0,5 s de recherche par question) passe après les rapides.
    return min(eligible, key=lambda r: (r["latency_ms"] > 500, r["ctx_tokens_at_5"],
                                        -r["mrr_at_10"]))


def save_results(results: list[dict], name: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", choices=["syntec", "nexalis"], default="syntec")
    parser.add_argument("--grid", choices=list(GRIDS), default="quick")
    parser.add_argument("--sizes", type=int, nargs="+", help="tailles (0 = par section)")
    parser.add_argument("--overlaps", type=float, nargs="+", help="ratios d'overlap, ex. 0.1")
    parser.add_argument("--min-tokens", type=int, nargs="+", default=[100])
    parser.add_argument("--reranker", action="store_true", help="évalue aussi avec reranker")
    parser.add_argument("--reranker-model", help="remplace RERANKER_MODEL")
    parser.add_argument("--hybrid", action="store_true", help="évalue aussi BM25 + vecteurs")
    parser.add_argument("--lexical-weight", type=float, help="poids de BM25 dans la fusion")
    parser.add_argument("--only-reranker", action="store_true")
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--name", help="nom du fichier de résultats")
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    if args.reranker_model:
        os.environ["RERANKER_MODEL"] = args.reranker_model
    if args.lexical_weight is not None:
        os.environ["HYBRID_LEXICAL_WEIGHT"] = str(args.lexical_weight)
    get_settings.cache_clear()
    grid = GRIDS[args.grid]
    rerank_modes = [True] if args.only_reranker else ([False, True] if args.reranker else [False])
    results = run(args.dataset, args.sizes or grid["sizes"], args.overlaps or grid["overlaps"],
                  args.min_tokens, rerank_modes, log_mlflow=not args.no_mlflow,
                  hybrid_modes=(False, True) if args.hybrid else (False,))
    path = save_results(results, args.name or f"retrieval_{args.dataset}_{args.grid}")
    choice = decide(results)
    print(f"\nRésultats : {path}")
    print("Configuration retenue (règle des 2 points) :", _format_row(choice))


if __name__ == "__main__":
    main()
