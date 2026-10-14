"""Itération 6 : compare des quantizations du LLM sur un échantillon fixe de questions.

Deux bancs d'essai, mêmes questions et mêmes critères que eval_answers :
- ollama  : modèles GGUF en local (q4_K_M, q8_0...) ; mémoire lue dans Ollama (RAM / VRAM) ;
- zerogpu : Ministral 3 8B sur le Space ZeroGPU en bf16, int8 et nf4 (bitsandbytes) ; le script
  change la variable QUANTIZATION du Space, attend son redémarrage, puis remet bf16 à la fin.
  Mémoire = VRAM maximale mesurée dans le Space.

Résultats : eval/results/quantization_<banc>_<date>.csv et MLflow (expérience « quantization »).

Usage :
    python -m eval.compare_quantization                              # GGUF en local
    python -m eval.compare_quantization --backend zerogpu            # bf16 / int8 / nf4
    python -m eval.compare_quantization --backend zerogpu --variants nf4
"""

import argparse
import csv
import statistics
import time
from datetime import datetime

import httpx

from app.config import get_settings
from app.rag.factory import build_retriever
from app.services.assistant import Assistant
from eval.common import MLFLOW_URI, RESULTS_DIR, read_jsonl
from eval.eval_answers import evaluate_question
from eval.eval_retrieval import NEXALIS_QUESTIONS

OLLAMA_MODELS = [
    "ministral-3:3b-instruct-2512-q4_K_M",
    "ministral-3:3b-instruct-2512-q8_0",
    "ministral-3:8b-instruct-2512-q4_K_M",
]
ZEROGPU_QUANTIZATIONS = ["bf16", "int8", "nf4"]

# Échantillon fixe : tous les types (factuelle, tableau, calcul, pièges, hors périmètre).
SAMPLE = ["tt-01", "tt-02", "tt-09", "tdt-01", "tdt-04", "tdt-08", "cg-01", "cg-02", "cg-08",
          "cg-09", "mu-01", "mu-02", "mu-08", "it-02", "it-06", "la-01", "nf-01", "nf-03",
          "oos-01", "oos-04"]


# --------------------------------------------------------------------------- Ollama (local)


def ollama_memory(base_url: str, model: str) -> dict:
    """Mémoire du modèle chargé, d'après /api/ps (taille totale et part en VRAM)."""
    try:
        loaded = httpx.get(f"{base_url}/api/ps", timeout=5).json().get("models", [])
    except httpx.HTTPError:
        return {}
    for m in loaded:
        if m.get("name") == model or m.get("model") == model:
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            return {"memory_gb": round(size / 1024**3, 2), "vram_gb": round(vram / 1024**3, 2),
                    "gpu_share": round(vram / size, 2) if size else None}
    return {}


def ensure_model(base_url: str, model: str) -> None:
    """Télécharge le modèle dans Ollama s'il n'est pas déjà présent."""
    tags = {m["name"] for m in httpx.get(f"{base_url}/api/tags", timeout=10).json()["models"]}
    if model not in tags:
        print(f"Téléchargement de {model}…", flush=True)
        with httpx.stream("POST", f"{base_url}/api/pull", json={"model": model},
                          timeout=None) as response:
            for _ in response.iter_lines():
                pass


def ollama_variants(settings, names):
    from app.llm.ollama_client import OllamaClient

    for model in names:
        ensure_model(settings.ollama_base_url, model)
        llm = OllamaClient(settings.ollama_base_url, model, settings.llm_temperature,
                           settings.llm_max_tokens, timeout_s=600,
                           num_ctx=settings.ollama_num_ctx)
        llm.generate("Réponds OK.", "OK ?")  # chargement du modèle, hors mesure
        yield model, llm, lambda m=model: ollama_memory(settings.ollama_base_url, m)


# --------------------------------------------------------------------------- ZeroGPU (Space)


def set_space_quantization(settings, quantization: str, timeout: int = 1200) -> None:
    """Change la variable QUANTIZATION du Space et attend qu'il soit de nouveau en service."""
    from huggingface_hub import HfApi

    api = HfApi(token=settings.hf_token.get_secret_value())
    space = settings.llm_space_id
    current = api.get_space_variables(space).get("QUANTIZATION")
    if current is not None and current.value == quantization:
        return
    api.add_space_variable(space, "QUANTIZATION", quantization)  # redémarre le Space
    time.sleep(20)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stage = api.get_space_runtime(space).stage
        if stage == "RUNNING":
            return
        if stage.endswith("ERROR"):
            raise RuntimeError(f"Le Space ne redémarre pas en {quantization} : {stage}")
        time.sleep(15)
    raise TimeoutError(f"Le Space n'a pas redémarré en {quantization}")


def zerogpu_variants(settings, names):
    from app.llm.zerogpu_client import ZeroGPUClient

    try:
        for quantization in names:
            print(f"Space en {quantization}…", flush=True)
            set_space_quantization(settings, quantization)
            llm = ZeroGPUClient(settings.llm_space_id, settings.hf_token.get_secret_value())
            llm.generate("Réponds OK.", "OK ?")  # premier appel (allocation), hors mesure
            yield f"ministral-3-8b-{quantization} (ZeroGPU)", llm, dict
    finally:
        set_space_quantization(settings, "bf16")


# --------------------------------------------------------------------------- mesure


def run_variant(label, llm, retriever, questions, memory) -> tuple[dict, list[dict]]:
    assistant = Assistant(llm, retriever)
    results = []
    for q in questions:
        r = evaluate_question(assistant, q)
        results.append(r)
        print(f"  {label:<38} {'OK' if r['correct'] else 'KO'} {q['id']:<7} "
              f"{r['latency_ms']:>7} ms", flush=True)
    metas = [r.get("llm_meta") or {} for r in results]

    def median(key, scale=1.0, digits=2):
        values = [m[key] * scale for m in metas if m.get(key)]
        return round(statistics.median(values), digits) if values else None

    llm_ms = [r["timings_ms"]["llm"] for r in results if r.get("timings_ms", {}).get("llm")]
    vram = [m["peak_vram_gb"] for m in metas if m.get("peak_vram_gb")]
    row = {
        "model": label,
        "questions": len(results),
        "correct": sum(r["correct"] for r in results),
        "accuracy": round(sum(r["correct"] for r in results) / len(results), 3),
        "tokens_per_second": median("tokens_per_second", digits=1),
        "generation_seconds_p50": median("generation_seconds"),
        "llm_seconds_p50": round(statistics.median(llm_ms) / 1000, 1) if llm_ms else None,
        **({"vram_gb": max(vram)} if vram else {}),
        **memory(),
    }
    return row, results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backend", choices=["ollama", "zerogpu"], default="ollama")
    parser.add_argument("--variants", nargs="+", help="modèles Ollama ou quantizations ZeroGPU")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    questions = [q for q in read_jsonl(NEXALIS_QUESTIONS) if q["id"] in SAMPLE]
    retriever = build_retriever(settings)
    if args.backend == "ollama":
        variants = ollama_variants(settings, args.variants or OLLAMA_MODELS)
    else:
        variants = zerogpu_variants(settings, args.variants or ZEROGPU_QUANTIZATIONS)

    rows = []
    for label, llm, memory in variants:
        row, _ = run_variant(label, llm, retriever, questions, memory)
        rows.append(row)
        print(row, flush=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"quantization_{args.backend}_{datetime.now():%Y%m%d_%H%M}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Résultats : {path}")

    if not args.no_mlflow:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment("quantization")
        for row in rows:
            with mlflow.start_run(run_name=row["model"]):
                mlflow.log_params({"model": row["model"], "backend": args.backend,
                                   "questions": row["questions"]})
                mlflow.log_metrics({k: float(v) for k, v in row.items()
                                    if isinstance(v, int | float) and k != "questions"})


if __name__ == "__main__":
    main()
