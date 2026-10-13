"""Seuil de pertinence : peut-on refuser les questions hors périmètre sans appeler le LLM ?

Pour chaque question du jeu Nexalis, on mesure le meilleur score obtenu par la recherche (cosinus
BGE-M3, et score du reranker si activé). On cherche ensuite le seuil qui écarte le plus de
questions hors périmètre sans écarter de questions légitimes : sous ce seuil, l'assistant répond
« je ne sais pas » directement, sans consommer de GPU.

Usage :
    python -m eval.analyze_gating
    python -m eval.analyze_gating --reranker-model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
"""

import argparse
import os

from app.config import get_settings
from app.rag.factory import build_retriever
from eval.common import read_jsonl
from eval.eval_retrieval import NEXALIS_QUESTIONS


def best_threshold(inside: list[float], outside: list[float]) -> tuple[float, int, int]:
    """Seuil qui maximise les hors-périmètre écartés sans écarter de question légitime ;
    renvoie (seuil, hors-périmètre écartés, légitimes écartées)."""
    candidates = sorted(set(inside + outside))
    best = (0.0, 0, 0)
    for t in candidates:
        lost = sum(1 for s in inside if s < t)
        caught = sum(1 for s in outside if s < t)
        if lost == 0 and caught > best[1]:
            best = (t, caught, lost)
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reranker-model")
    parser.add_argument("--no-reranker", action="store_true")
    args = parser.parse_args()
    if args.reranker_model:
        os.environ["RERANKER_MODEL"] = args.reranker_model
        os.environ["RERANKER_ENABLED"] = "true"
    if args.no_reranker:
        os.environ["RERANKER_ENABLED"] = "false"
    os.environ["RERANK_MIN_SCORE"] = "0"
    os.environ["RETRIEVAL_MIN_SCORE"] = "0"
    get_settings.cache_clear()

    retriever = build_retriever(get_settings())
    scores: dict[str, dict[str, list[float]]] = {"cosinus": {"in": [], "out": []},
                                                 "reranker": {"in": [], "out": []}}
    for q in read_jsonl(NEXALIS_QUESTIONS):
        result = retriever.search(q["question"])
        group = "out" if q["type"] == "hors_perimetre" else "in"
        scores["cosinus"][group].append(max(c.score for c in result.chunks))
        if retriever.reranker:
            scores["reranker"][group].append(max(c.rerank_score for c in result.chunks))

    for name, groups in scores.items():
        if not groups["in"]:
            continue
        inside, outside = groups["in"], groups["out"]
        threshold, caught, _ = best_threshold(inside, outside)
        print(f"\n{name} ({retriever.reranker.model_name if name == 'reranker' else 'BGE-M3'})")
        med_in, med_out = sorted(inside)[len(inside) // 2], sorted(outside)[len(outside) // 2]
        print(f"  légitimes      : min={min(inside):.3f}  médiane={med_in:.3f}")
        print(f"  hors périmètre : max={max(outside):.3f}  médiane={med_out:.3f}")
        print(f"  seuil sans perte : {threshold:.3f} -> {caught}/{len(outside)} hors périmètre "
              "refusés sans appel au LLM")
        print("  seuil   hors périmètre écartés   légitimes écartées")
        for t in [round(threshold - d, 3) for d in (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)]:
            out = sum(1 for s in outside if s < t)
            lost = sum(1 for s in inside if s < t)
            print(f"  {t:.3f}   {out:>2}/{len(outside)}                     {lost}/{len(inside)}")


if __name__ == "__main__":
    main()
