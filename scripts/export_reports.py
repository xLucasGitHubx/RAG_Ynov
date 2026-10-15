"""Consolide les résultats d'évaluation et de tests pour l'interface web (/ui).

Lit eval/results/ (grilles de retrieval, évaluations de bout en bout, seuil de refus, benchmark
des rerankers), les jeux de questions et le rapport pytest, puis écrit app/reports/dashboard.json,
servi par GET /api/reports. Aucun modèle n'est chargé : ce script ne fait que relire des fichiers.

Usage :
    python -m scripts.export_reports              # relance aussi pytest
    python -m scripts.export_reports --skip-tests # garde le dernier rapport pytest
"""

import argparse
import csv
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.prompts import PROMPT_VERSION
from app.security.pii import LABELS, detect_pii, mask_pii
from eval.common import RESULTS_DIR, read_jsonl
from eval.eval_answers import keywords_ok
from eval.eval_retrieval import NEXALIS_QUESTIONS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "reports" / "dashboard.json"
JUNIT = RESULTS_DIR / "pytest.xml"
PII_MESSAGES = ROOT / "eval" / "pii_messages.jsonl"
SYNTEC_QUERIES = ROOT / "eval" / "syntec" / "queries.jsonl"

# Évaluations de bout en bout présentées dans l'interface (un run peut fusionner plusieurs
# fichiers : les questions relancées remplacent les échecs techniques du premier fichier).
ANSWER_RUNS = [
    {"version": "v2", "label": "Prompt v2",
     "files": ["answers_ollama_20261013_1415.jsonl"],
     "note": "Réponses notées avec les critères corrigés (tdt-08, mu-05)."},
    {"version": "v3", "label": "Prompt v3 (retenu)",
     "files": ["answers_ollama_v3_20261013_1527.jsonl", "answers_ollama_v3_20261013_1531.jsonl",
               "answers_ollama_v3_20261014_1053.jsonl"],
     "note": "it-07 et nf-03 relancées le 14/10 (Ollama en échec la veille, surchauffe)."},
]

TYPE_LABELS = {
    "factuelle": "Factuelle",
    "tableau": "Information dans un tableau",
    "calcul": "Calcul",
    "piege_version": "Piège : version obsolète",
    "piege_contradiction": "Piège : convention ou accord",
    "piege_tableau": "Piège : tableau seul",
    "hors_perimetre": "Hors périmètre",
}

METRICS = ["recall_at_1", "recall_at_3", "recall_at_5", "recall_at_8", "mrr_at_10",
           "ctx_tokens_at_5", "latency_ms", "n_chunks"]


# --------------------------------------------------------------------------- retrieval


def read_csv(name: str) -> list[dict]:
    path = RESULTS_DIR / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for row in rows:
        clean = {
            "dataset": row["dataset"],
            "chunk_size": row["chunk_size"],
            "overlap": float(row["overlap"]),
            "hybrid": row.get("hybrid", "False") not in ("False", ""),
            "lexical_weight": _weight(row.get("hybrid")),
            "reranker": None if row["reranker"] == "False" else row["reranker"],
        }
        clean |= {m: float(row[m]) for m in METRICS if row.get(m) not in (None, "")}
        out.append(clean)
    return out


def _weight(value: str | None) -> float | None:
    if value in (None, "", "False"):
        return None
    return 1.0 if value == "True" else float(value)


def retrieval_section() -> dict:
    syntec = read_csv("retrieval_syntec_full.csv")
    nexalis_vector = [r for r in read_csv("retrieval_nexalis_minilm.csv")]
    hybrid = read_csv("retrieval_nexalis_hybrid.csv")
    bge = read_csv("retrieval_nexalis_bge_reranker.csv")

    def pick(rows, size="256", hybrid_=False, reranker=None):
        for r in rows:
            if (r["chunk_size"] == size and r["hybrid"] == hybrid_
                    and (r["reranker"] or None) == reranker):
                return r
        return None

    minilm = "mmarco-mMiniLMv2-L12-H384-v1"
    comparison = [
        ("Vecteurs seuls", pick(hybrid), "vector"),
        ("Vecteurs + reranker mMiniLMv2", pick(hybrid, reranker=minilm), "minilm"),
        ("Vecteurs + reranker bge-v2-m3", pick(bge, reranker="bge-reranker-v2-m3"), "bge"),
        ("Hybride BM25 + vecteurs", pick(hybrid, hybrid_=True), "hybrid"),
        ("Hybride + reranker mMiniLMv2", pick(hybrid, hybrid_=True, reranker=minilm),
         "hybrid_minilm"),
    ]
    weights = []
    for dataset in ("nexalis", "syntec"):
        for w in ("0.3", "0.5", "0.7"):
            row = pick(read_csv(f"retrieval_{dataset}_hybrid_w{w}.csv"), hybrid_=True)
            if row:
                weights.append(row)
        base = read_csv(f"retrieval_{dataset}_hybrid.csv")
        weights += [r for r in (pick(base), pick(base, hybrid_=True)) if r]

    gating_path = RESULTS_DIR / "gating.json"
    bench_path = RESULTS_DIR / "bench_reranker.json"
    return {
        "syntec_grid": syntec,
        "nexalis_sizes": [r for r in nexalis_vector if r["reranker"] is None],
        "nexalis_sizes_minilm": [r for r in nexalis_vector if r["reranker"]],
        "syntec_hybrid": read_csv("retrieval_syntec_hybrid.csv"),
        "comparison": [{"label": label, "key": key, **row}
                       for label, row, key in comparison if row],
        "lexical_weights": weights,
        "gating": json.loads(gating_path.read_text(encoding="utf-8"))
        if gating_path.exists() else None,
        "reranker_bench": json.loads(bench_path.read_text(encoding="utf-8"))
        if bench_path.exists() else None,
    }


# --------------------------------------------------------------------------- réponses


# Première évaluation sur ZeroGPU, avant l'ajout des 11 fiches Syntec (10 documents, 68 questions) :
# gardée pour vérifier que l'extension du corpus ne dégrade pas les réponses d'origine.
ZEROGPU_10_DOCS = "answers_zerogpu_v3_20261014_1407.jsonl"


def answer_runs() -> list[dict]:
    """Runs fixes (local) + les évaluations sur ZeroGPU (avant et après l'extension du corpus)."""
    specs = list(ANSWER_RUNS)
    if (RESULTS_DIR / ZEROGPU_10_DOCS).exists():
        specs.append({
            "version": "zerogpu-10docs", "label": "8B · ZeroGPU, 10 documents",
            "files": [ZEROGPU_10_DOCS],
            "note": "Ministral 3 8B bf16 sur le Space Hugging Face, corpus initial "
                    "de 10 documents.",
        })
    zerogpu = sorted(p for p in RESULTS_DIR.glob("answers_zerogpu_*.jsonl")
                     if p.name != ZEROGPU_10_DOCS)
    if zerogpu:
        specs.append({
            "version": "zerogpu", "label": "8B · ZeroGPU, 21 documents",
            "files": [zerogpu[-1].name],
            "note": "Modèle de production : Ministral 3 8B bf16 sur le Space Hugging Face, corpus "
                    "étendu aux 11 fiches Syntec (81 questions).",
        })
    return specs


# --------------------------------------------------------------------------- juge LLM


def latest_judgements() -> dict[str, dict]:
    """Dernier jugement par fichier de réponses : {fichier: {"summary", "rows"}}."""
    found: dict[str, dict] = {}
    for summary_path in sorted(RESULTS_DIR.glob("judge_*.summary.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        stem = summary_path.name.removesuffix(".summary.json")
        rows_path = summary_path.with_name(stem + ".jsonl")
        rows = {r["id"]: r for r in read_jsonl(rows_path)} if rows_path.exists() else {}
        found[summary["answers_file"]] = {"summary": summary, "rows": rows}
    return found


def quantization_section() -> list[dict]:
    """Dernier banc de quantization par environnement (local GGUF, ZeroGPU)."""
    latest: dict[str, Path] = {}
    for path in sorted(RESULTS_DIR.glob("quantization_*.csv")):
        backend = "zerogpu" if "zerogpu" in path.name else "ollama"
        latest[backend] = path
    rows = []
    for backend, path in latest.items():
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                clean = {"backend": backend}
                for key, value in row.items():
                    try:
                        clean[key] = float(value) if value not in ("", None) else None
                    except ValueError:
                        clean[key] = value
                rows.append(clean)
    return rows


def answers_section() -> dict:
    questions = {q["id"]: q for q in read_jsonl(NEXALIS_QUESTIONS)}
    judgements = latest_judgements()
    runs = []
    for spec in answer_runs():
        judgement = next((judgements[f] for f in spec["files"] if f in judgements), None)
        rows: dict[str, dict] = {}
        for name in spec["files"]:
            path = RESULTS_DIR / name
            if not path.exists():
                continue
            for row in read_jsonl(path):
                if row["id"] not in rows or not row.get("error"):
                    rows[row["id"]] = row
        if not rows:
            continue
        items = []
        for qid, q in questions.items():
            row = rows.get(qid)
            if row is None:
                continue
            item = {
                "id": qid,
                "type": q["type"],
                "type_label": TYPE_LABELS.get(q["type"], q["type"]),
                "question": q["question"],
                "expected": q.get("answer"),
                "document": q.get("document"),
                "answer": row.get("answer"),
                "error": bool(row.get("error")),
                "refused": bool(row.get("refused")),
                "llm_called": row.get("llm_called", True),
                "sources": sorted(set(row.get("sources") or [])),
                "latency_ms": row.get("latency_ms"),
                "prompt_tokens": row.get("prompt_tokens"),
                "completion_tokens": row.get("completion_tokens"),
                "generation_seconds": (row.get("llm_meta") or {}).get("generation_seconds"),
            }
            if row.get("error"):
                item["status"] = "erreur"
            elif q["type"] == "hors_perimetre":
                item["status"] = "ok" if row.get("refused") else "ko"
            else:  # critères actuels de eval/questions.jsonl (re-notation sans relancer le LLM)
                ok = keywords_ok(row.get("answer") or "", q.get("keywords", []))
                item["status"] = "ok" if ok and not row.get("refused") else "ko"
                item["source_cited"] = q["document"] in (row.get("sources") or [])
            verdict = (judgement or {}).get("rows", {}).get(qid)
            if verdict and verdict.get("verdict"):
                item["judge"] = {k: verdict.get(k) for k in
                                 ("verdict", "exactitude", "fidelite", "citation", "justification")}
            items.append(item)
        run = {**{k: spec[k] for k in ("version", "label", "note")},
               "summary": summarize_answers(items), "items": items}
        if judgement:
            run["judge"] = judgement["summary"]
        runs.append(run)
    return {"runs": runs, "type_labels": TYPE_LABELS}


def summarize_answers(items: list[dict]) -> dict:
    answerable = [i for i in items if i["type"] != "hors_perimetre" and i["status"] != "erreur"]
    oos = [i for i in items if i["type"] == "hors_perimetre" and i["status"] != "erreur"]
    by_type: dict[str, list] = defaultdict(list)
    for i in answerable:
        by_type[i["type"]].append(i)
    latencies = sorted(i["latency_ms"] for i in items
                       if i["status"] != "erreur" and i.get("llm_called") and i["latency_ms"])
    gpu = sorted(i["generation_seconds"] for i in items if i.get("generation_seconds"))
    return {
        "generation_seconds_p50": gpu[len(gpu) // 2] if gpu else None,
        "evaluated": len(answerable),
        "correct": sum(i["status"] == "ok" for i in answerable),
        "accuracy": _ratio(answerable, lambda i: i["status"] == "ok"),
        "false_refusals": sum(i["refused"] for i in answerable),
        "source_cited": _ratio(answerable, lambda i: i.get("source_cited")),
        "oos_total": len(oos),
        "oos_refused": sum(i["refused"] for i in oos),
        "oos_without_llm": sum(not i["llm_called"] for i in oos),
        "errors": sum(i["status"] == "erreur" for i in items),
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "by_type": {t: {"total": len(v), "correct": sum(i["status"] == "ok" for i in v)}
                    for t, v in by_type.items()},
    }


def _ratio(items, predicate) -> float | None:
    return sum(1 for i in items if predicate(i)) / len(items) if items else None


# --------------------------------------------------------------------------- coûts


# Volume de référence du budget (docs/estimation_budget.md) : 1 000 utilisateurs, 3 questions par
# jour, 95 % des questions appellent le LLM, 22 jours ouvrés, 10 heures d'activité par jour.
VOLUME = {"users": 1000, "questions": 3, "llm_share": 0.95, "days": 22, "hours": 10}


def costs_section(runs: list[dict]) -> dict | None:
    """Coût d'usage des LLM en euros, à partir des tokens et du temps GPU mesurés en production."""
    from eval.costs import (
        L4_EUR_PER_HOUR,
        RATE_SOURCE,
        T4_EUR_PER_HOUR,
        TOKEN_PRICES,
        ZEROGPU_EUR_PER_SECOND,
        from_usd,
        token_cost_eur,
    )
    from scripts.finops import estimate

    all_runs = sorted(RESULTS_DIR.glob("answers_zerogpu_*.jsonl"))
    paths = [p for p in all_runs if p.name != ZEROGPU_10_DOCS] or all_runs
    if not paths:
        return None
    rows = [r for r in read_jsonl(paths[-1]) if r.get("llm_called") and r.get("prompt_tokens")]
    if not rows:
        return None
    prompt = sum(r["prompt_tokens"] for r in rows) / len(rows)
    completion = sum(r.get("completion_tokens") or 0 for r in rows) / len(rows)
    gpu = sorted((r.get("llm_meta") or {}).get("generation_seconds") or 0 for r in rows)
    gpu_p50 = gpu[len(gpu) // 2]
    v = VOLUME
    answers_month = v["users"] * v["questions"] * v["llm_share"] * v["days"]
    est = estimate(v["users"], v["questions"], gpu_p50, v["llm_share"], v["days"], v["hours"], 2, 4)

    def per_token(model: str) -> float:
        return token_cost_eur(model, prompt, completion)

    options = [
        {"key": "zerogpu", "label": "ZeroGPU (Space Hugging Face)", "model": "Ministral 3 8B bf16",
         "billing": "temps GPU", "self_hosted": True,
         "per_answer_eur": gpu_p50 * ZEROGPU_EUR_PER_SECOND,
         "monthly_eur": from_usd(est["zerogpu_month"]),
         "note": "40 min de GPU incluses par jour (compte PRO), puis 1 $ les 10 minutes. Aucune "
                 "garantie de disponibilité : outil de démonstration."},
        {"key": "l4", "label": "GPU dédié L4 24 Go, 10 h par jour", "model": "Ministral 3 8B bf16",
         "billing": "heure de GPU", "self_hosted": True,
         "per_answer_eur": L4_EUR_PER_HOUR * v["hours"] * v["days"] / answers_month,
         "monthly_eur": L4_EUR_PER_HOUR * v["hours"] * v["days"],
         "note": "Coût fixe, quel que soit le volume : recommandé pour la production."},
        {"key": "t4", "label": "GPU dédié T4 16 Go, 10 h par jour", "model": "Ministral 3 8B nf4",
         "billing": "heure de GPU", "self_hosted": True,
         "per_answer_eur": T4_EUR_PER_HOUR * v["hours"] * v["days"] / answers_month,
         "monthly_eur": T4_EUR_PER_HOUR * v["hours"] * v["days"],
         "note": "Possible grâce au nf4 (6,7 Go, sans perte mesurée) ; débit de la T4 à mesurer."},
    ]
    for model in ("ministral-8b-2512", "mistral-small-2603", "mistral-large-2512"):
        price = TOKEN_PRICES[model]
        options.append({
            "key": model, "label": price.label.split(" · ")[0],
            "model": price.label.split(" · ")[1],
            "billing": "tokens", "self_hosted": False,
            "per_answer_eur": per_token(model), "monthly_eur": per_token(model) * answers_month,
            "note": ("Même modèle que la production, servi par Mistral (France) : bien moins "
                     "cher à ce volume, mais contraire à la contrainte d'auto-hébergement."
                     if model == "ministral-8b-2512" else
                     "Modèle plus grand, pour comparaison."),
        })
    judge = next((r["judge"] for r in reversed(runs) if r.get("judge")), None)
    eval_rows = read_jsonl(paths[-1])
    eval_gpu = sum((r.get("llm_meta") or {}).get("generation_seconds") or 0 for r in eval_rows)
    return {
        "volume": {**v, "answers_per_month": answers_month},
        "measured": {"prompt_tokens_mean": prompt, "completion_tokens_mean": completion,
                     "gpu_seconds_p50": gpu_p50, "answers": len(rows), "file": paths[-1].name},
        "options": options,
        "infrastructure": {"label": "API sur Azure Container Apps et registre",
                           "monthly_eur": from_usd(est["api_month"])},
        "prices": [{"model": m, **vars(p)} for m, p in TOKEN_PRICES.items()],
        "evaluation": {
            "questions": len(eval_rows),
            "gpu_seconds": eval_gpu,
            "gpu_eur_equivalent": eval_gpu * ZEROGPU_EUR_PER_SECOND,
            "judge_model": judge.get("judge_model") if judge else None,
            "judge_eur": judge.get("cost_eur") if judge else None,
            "judge_tokens": ((judge.get("tokens_in", 0) + judge.get("tokens_out", 0))
                             if judge else None),
        },
        "rate_source": RATE_SOURCE,
    }


# --------------------------------------------------------------------------- sécurité


def security_section() -> dict:
    messages = []
    for m in read_jsonl(PII_MESSAGES):
        kinds = sorted({x.kind for x in detect_pii(m["message"])})
        messages.append({"id": m["id"], "type": m["type"], "label": LABELS[m["type"]],
                         "detected": kinds, "blocked": m["type"] in kinds,
                         "masked": mask_pii(m["message"])})
    legit = [q["question"] for q in read_jsonl(NEXALIS_QUESTIONS)]
    legit += [q["question"] for q in read_jsonl(SYNTEC_QUERIES)]
    false_positives = [q for q in legit if detect_pii(q)]
    return {
        "messages": messages,
        "blocked": sum(m["blocked"] for m in messages),
        "legit_questions": len(legit),
        "false_positives": len(false_positives),
        "labels": LABELS,
    }


# --------------------------------------------------------------------------- tests


def run_pytest() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={JUNIT}"],
                   cwd=ROOT, check=False)


def tests_section() -> dict | None:
    if not JUNIT.exists():
        return None
    root = ET.parse(JUNIT).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    files: dict[str, list] = defaultdict(list)
    for case in suite.iter("testcase"):
        module = case.get("classname", "").split(".")[-1]
        status = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        files[module].append({"name": case.get("name"), "status": status,
                              "seconds": float(case.get("time", 0))})
    total = sum(len(v) for v in files.values())
    failed = sum(t["status"] == "failed" for v in files.values() for t in v)
    return {
        "timestamp": suite.get("timestamp"),
        "total": total,
        "failed": failed,
        "passed": total - failed - sum(t["status"] == "skipped" for v in files.values()
                                        for t in v),
        "seconds": float(suite.get("time", 0)),
        "files": [{"file": f"tests/{name}.py", "tests": tests}
                  for name, tests in sorted(files.items())],
    }


# --------------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    if not args.skip_tests:
        run_pytest()

    settings = get_settings()
    answers = answers_section()
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt_version": PROMPT_VERSION,
        "datasets": {
            "syntec_questions": len(read_jsonl(SYNTEC_QUERIES)),
            "nexalis_questions": len(read_jsonl(NEXALIS_QUESTIONS)),
            "pii_messages": len(read_jsonl(PII_MESSAGES)),
        },
        "retained": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "hybrid_search": settings.hybrid_search,
            "lexical_weight": settings.hybrid_lexical_weight,
            "reranker": settings.reranker_model if settings.reranker_enabled else None,
            "top_k": settings.retrieval_top_k,
            "min_score": settings.retrieval_min_score,
            "embedding_model": settings.embedding_model,
            "llm_model": settings.ollama_model,
        },
        "retrieval": retrieval_section(),
        "answers": answers,
        "costs": costs_section(answers["runs"]),
        "quantization": quantization_section(),
        "security": security_section(),
        "tests": tests_section(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tests = report["tests"] or {}
    print(f"Rapport écrit : {OUTPUT.relative_to(ROOT)} "
          f"({OUTPUT.stat().st_size // 1024} Ko, {tests.get('total', 0)} tests, "
          f"{len(report['answers']['runs'])} évaluations de réponses)")


if __name__ == "__main__":
    main()
