"""Évaluation des réponses par un LLM juge (« LLM as a judge »).

Le critère historique (eval_answers) vérifie des mots-clés : strict sur les chiffres, mais aveugle
à une réponse juste formulée autrement, ou à une phrase inventée à côté du bon chiffre. Le juge, un
modèle plus grand et d'une autre famille que le modèle évalué, lit pour chaque question :
la question, la réponse de référence, les extraits que l'assistant avait sous les yeux et sa
réponse. Il note :

- exactitude (1 à 5) : même information que la référence (chiffres, durées, conditions) ;
- fidélité (1 à 5) : chaque affirmation est appuyée par les extraits (pas d'hallucination) ;
- citation : au moins un document cité contient bien l'information ;
- verdict : correcte, partielle ou incorrecte, avec une justification d'une phrase.

L'accord avec le critère par mots-clés est mesuré (pourcentage et kappa de Cohen) : c'est ce qui
permet de faire confiance au juge, ou de repérer ses désaccords à relire.

Entrée : un fichier eval/results/answers_*.jsonl produit par eval_answers (avec les extraits).
Sorties : eval/results/judge_*.jsonl (une ligne par question), judge_*.summary.json (synthèse,
coût en euros) et MLflow (expérience « judge »).

Usage :
    python -m eval.judge eval/results/answers_zerogpu_v3_AAAAMMJJ_HHMM.jsonl
    python -m eval.judge FICHIER --backend mistral --model mistral-large-2512 --pause 1.5
    python -m eval.judge FICHIER --backend hf --bill-to ynov
    python -m eval.judge FICHIER --backend zerogpu      # même modèle que la production : biaisé
"""

# Le prompt du juge est un texte : ses lignes restent entières pour rester lisibles.
# ruff: noqa: E501

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from eval.common import MLFLOW_URI, RESULTS_DIR, read_jsonl
from eval.costs import RATE_SOURCE, TOKEN_PRICES, gpu_cost_eur, token_cost_eur

DEFAULT_MODELS = {
    "hf": "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra",
    "mistral": "mistral-large-2512",
}
VERDICTS = ("correcte", "partielle", "incorrecte")
CONTEXT_CHARS = 1800  # par extrait : les chunks font 256 tokens, cette limite ne coupe presque rien

SYSTEM_PROMPT = """Tu es un évaluateur exigeant d'un assistant RH et IT qui répond aux salariés à partir de documents internes.

Tu reçois une question, la réponse de référence rédigée par un expert, les extraits de documents que l'assistant avait sous les yeux, et la réponse de l'assistant. Évalue la réponse de l'assistant :

1. exactitude (entier de 1 à 5) : donne-t-elle la même information que la référence (chiffres, durées, conditions) ? 5 = exacte et complète ; 4 = exacte, un détail secondaire manque ; 3 = en partie exacte ou incomplète sur un point important ; 2 = majoritairement fausse ; 1 = fausse, ou refus alors que la réponse était dans les extraits.
2. fidelite (entier de 1 à 5) : chaque affirmation est-elle appuyée par les extraits ? 5 = tout vient des extraits ; 3 = un ajout non vérifiable mais plausible ; 1 = information inventée ou contraire aux extraits. Un refus est fidèle.
3. citation (true ou false) : la réponse cite-t-elle, entre crochets, au moins un document qui contient effectivement l'information donnée ? Pour un refus justifié, true.
4. verdict : "correcte" si exactitude >= 4 et fidelite >= 4 ; "partielle" si la réponse est utile mais incomplète ou imprécise ; "incorrecte" sinon.

Questions hors périmètre : la référence indique que l'information n'est pas dans les documents. La bonne réponse est alors un refus poli, sans rien inventer : verdict "correcte" (exactitude 5, fidelite 5). Si l'assistant invente une réponse, verdict "incorrecte".

Ne juge pas le style ni la longueur. Une formulation différente de la référence est acceptable si l'information est la même.

Réponds uniquement par un objet JSON sur une seule ligne, sans texte autour :
{"exactitude": 1-5, "fidelite": 1-5, "citation": true|false, "verdict": "correcte|partielle|incorrecte", "justification": "une phrase en français"}"""


def build_user_prompt(row: dict, question: dict) -> str:
    extracts = []
    for i, ctx in enumerate(row.get("contexts") or [], start=1):
        text = (ctx.get("text") or "")[:CONTEXT_CHARS]
        extracts.append(
            f"[Extrait {i}] Document : {ctx.get('document')} — {ctx.get('section')}\n{text}"
        )
    reference = (
        question.get("answer")
        or "L'information n'est pas dans les documents : l'assistant doit refuser."
    )
    return (
        f"QUESTION :\n{row['question']}\n\n"
        f"RÉPONSE DE RÉFÉRENCE :\n{reference}\n\n"
        f"EXTRAITS FOURNIS À L'ASSISTANT :\n"
        + ("\n\n".join(extracts) or "(aucun extrait : refus sans appel au modèle)")
        + f"\n\nRÉPONSE DE L'ASSISTANT :\n{row.get('answer') or ''}"
    )


def parse_verdict(text: str) -> dict:
    """Extrait l'objet JSON de la réponse du juge et le valide."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"pas de JSON dans la réponse du juge : {text[:120]!r}")
    data = json.loads(match.group(0))
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict inconnu : {verdict!r}")
    scores = {}
    for key in ("exactitude", "fidelite"):
        value = int(data.get(key))
        if not 1 <= value <= 5:
            raise ValueError(f"{key} hors de l'échelle : {value}")
        scores[key] = value
    citation = data.get("citation")
    if isinstance(citation, str):
        citation = citation.strip().lower() in ("true", "oui", "vrai")
    return {
        "verdict": verdict,
        **scores,
        "citation": bool(citation),
        "justification": str(data.get("justification", "")).strip(),
    }


# --------------------------------------------------------------------------- fournisseurs


class HFRouterJudge:
    """Fournisseurs d'inférence Hugging Face (API compatible OpenAI), avec le jeton HF_TOKEN."""

    name = "hf"

    def __init__(self, model: str, token: str, bill_to: str | None = None) -> None:
        import httpx

        self.model = model
        headers = {"Authorization": f"Bearer {token}"}
        if bill_to:
            headers["X-HF-Bill-To"] = bill_to
        self._client = httpx.Client(
            base_url="https://router.huggingface.co/v1", headers=headers, timeout=180
        )

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        response = self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code} : {response.text[:200]}")
        data = response.json()
        usage = data.get("usage") or {}
        return (
            data["choices"][0]["message"]["content"],
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )


class MistralJudge:
    """API Mistral. L'offre gratuite limite fortement le débit : nouvelles tentatives espacées."""

    name = "mistral"

    def __init__(self, model: str, api_key: str) -> None:
        from mistralai.client import Mistral

        self.model = model
        self._client = Mistral(api_key=api_key, timeout_ms=180_000)

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        for attempt in range(6):
            try:
                response = self._client.chat.complete(
                    model=self.model,
                    temperature=0,
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                usage = response.usage
                return (
                    response.choices[0].message.content,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                )
            except Exception as exc:  # limite de débit (429) : on attend et on réessaie
                if "429" not in str(exc) or attempt == 5:
                    raise
                time.sleep(2**attempt * 5)
        raise RuntimeError("API Mistral indisponible")


class LocalJudge:
    """Juge servi par un fournisseur de l'application (zerogpu, ollama). Avec zerogpu, c'est le
    même modèle que celui évalué : le résultat est biaisé en sa faveur, à n'utiliser que faute
    de mieux."""

    def __init__(self, provider: str) -> None:
        from app.config import get_settings
        from app.llm import build_llm_client

        settings = get_settings().model_copy(
            update={"llm_provider": provider, "llm_temperature": 0.0}
        )
        self._llm = build_llm_client(settings)
        self.name = provider
        self.model = getattr(self._llm, "model", provider)
        self.gpu_seconds = 0.0  # temps de GPU de la question en cours (ZeroGPU)

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        generation = self._llm.generate(system, user)
        self.gpu_seconds += (generation.meta or {}).get("generation_seconds") or 0.0
        return generation.text, generation.prompt_tokens or 0, generation.completion_tokens or 0

    def row_cost(self, tokens_in: int, tokens_out: int) -> float | None:
        """Sur ZeroGPU, le coût se compte en temps de GPU (au tarif hors quota)."""
        if self.name != "zerogpu":
            return None
        cost, self.gpu_seconds = gpu_cost_eur(self.gpu_seconds), 0.0
        return cost


def build_judge(backend: str, model: str | None, bill_to: str | None):
    from app.config import get_settings

    settings = get_settings()
    if backend == "hf":
        if not settings.hf_token:
            raise SystemExit("HF_TOKEN manquant dans .env")
        return HFRouterJudge(
            model or DEFAULT_MODELS["hf"], settings.hf_token.get_secret_value(), bill_to
        )
    if backend == "mistral":
        if not settings.mistral_api_key:
            raise SystemExit("MISTRAL_API_KEY manquant dans .env")
        return MistralJudge(
            model or DEFAULT_MODELS["mistral"], settings.mistral_api_key.get_secret_value()
        )
    return LocalJudge(backend)


# --------------------------------------------------------------------------- synthèse


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Accord entre deux jugements binaires, corrigé du hasard (1 = accord parfait)."""
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def summarize(rows: list[dict]) -> dict:
    judged = [r for r in rows if r.get("verdict")]
    answerable = [r for r in judged if r["type"] != "hors_perimetre"]
    counts = {v: sum(1 for r in judged if r["verdict"] == v) for v in VERDICTS}
    mean = lambda items, key: (sum(r[key] for r in items) / len(items)) if items else None  # noqa: E731
    judge_ok = [r["verdict"] == "correcte" for r in judged]
    keyword_ok = [bool(r["keyword_correct"]) for r in judged]
    tokens_in = sum(r.get("tokens_in", 0) for r in rows)
    tokens_out = sum(r.get("tokens_out", 0) for r in rows)
    costs = [r["cost_eur"] for r in rows if r.get("cost_eur") is not None]
    return {
        "judged": len(judged),
        "failed": len(rows) - len(judged),
        "verdicts": counts,
        "correct_rate": counts["correcte"] / len(judged) if judged else None,
        "exactitude_mean": mean(answerable, "exactitude"),
        "fidelite_mean": mean(answerable, "fidelite"),
        "citation_rate": (
            sum(r["citation"] for r in answerable) / len(answerable) if answerable else None
        ),
        "agreement_keywords": (
            sum(x == y for x, y in zip(judge_ok, keyword_ok, strict=True)) / len(judged)
            if judged
            else None
        ),
        "kappa_keywords": cohen_kappa(judge_ok, keyword_ok),
        "disagreements": [
            r["id"] for r in judged if (r["verdict"] == "correcte") != r["keyword_correct"]
        ],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_eur": sum(costs) if costs else None,
    }


def keyword_verdict(answer: dict, question: dict) -> bool:
    """Verdict du critère par mots-clés, avec les critères actuels de eval/questions.jsonl
    (et non ceux en vigueur au moment de l'évaluation) : les deux jugements restent comparables."""
    from eval.eval_answers import keywords_ok

    if answer.get("answer") is None:
        return False
    if question["type"] == "hors_perimetre":
        return bool(answer.get("refused"))
    return keywords_ok(answer["answer"], question.get("keywords", [])) and not answer.get("refused")


def resummarize(judge_file: Path) -> None:
    """Recalcule l'accord avec les mots-clés et la synthèse d'un jugement existant, sans relancer
    le juge (utile après la correction d'un critère par mots-clés)."""
    from eval.eval_retrieval import NEXALIS_QUESTIONS

    summary_path = judge_file.with_suffix(".summary.json")
    previous = json.loads(summary_path.read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in read_jsonl(NEXALIS_QUESTIONS)}
    answers = {r["id"]: r for r in read_jsonl(RESULTS_DIR / previous["answers_file"])}
    rows = read_jsonl(judge_file)
    for row in rows:
        row["keyword_correct"] = keyword_verdict(answers[row["id"]], questions[row["id"]])
    judge_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                          encoding="utf-8")
    summary = previous | summarize(rows)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for key in ("agreement_keywords", "kappa_keywords", "disagreements"):
        print(f"  {key:<20} {summary[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("answers", type=Path, help="fichier answers_*.jsonl à juger "
                        "(ou judge_*.jsonl avec --resummarize)")
    parser.add_argument("--resummarize", action="store_true",
                        help="recalcule la synthèse d'un jugement existant, sans appel au juge")
    parser.add_argument("--backend", choices=["hf", "mistral", "zerogpu", "ollama"], default="hf")
    parser.add_argument("--model", help="modèle du juge (défaut selon le fournisseur)")
    parser.add_argument("--bill-to", help="organisation Hugging Face à facturer (ex. ynov)")
    parser.add_argument("--pause", type=float, default=0.0, help="secondes entre deux appels")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    if args.resummarize:
        resummarize(args.answers)
        return

    from eval.eval_retrieval import NEXALIS_QUESTIONS

    questions = {q["id"]: q for q in read_jsonl(NEXALIS_QUESTIONS)}
    answers = read_jsonl(args.answers)
    if args.limit:
        answers = answers[: args.limit]
    if not any(r.get("contexts") for r in answers):
        raise SystemExit(
            "Ce fichier ne contient pas les extraits (évaluation antérieure) : "
            "relancez python -m eval.eval_answers."
        )
    judge = build_judge(args.backend, args.model, args.bill_to)
    print(f"Juge : {judge.name} · {judge.model} — {len(answers)} réponses", flush=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    slug = (
        re.sub(r"[^A-Za-z0-9]+", "-", judge.model.split("/")[-1].split(":")[0]).strip("-").lower()
    )
    out = RESULTS_DIR / f"judge_{args.answers.stem}__{slug}_{stamp}.jsonl"
    rows = []
    start = time.perf_counter()
    with out.open("w", encoding="utf-8") as f:
        for answer in answers:
            q = questions[answer["id"]]
            row = {
                "id": answer["id"],
                "type": answer["type"],
                "keyword_correct": keyword_verdict(answer, q),
            }
            if answer.get("answer") is None:
                row["error"] = "réponse non générée"
            else:
                user = build_user_prompt(answer, q)
                for _ in range(2):
                    try:
                        text, tin, tout = judge.complete(SYSTEM_PROMPT, user)
                        row["tokens_in"] = row.get("tokens_in", 0) + tin
                        row["tokens_out"] = row.get("tokens_out", 0) + tout
                        row |= parse_verdict(text)
                        row.pop("error", None)
                        break
                    except Exception as exc:  # JSON invalide, erreur réseau : une seconde chance
                        row["error"] = str(exc)[:200]
                        if "HTTP 402" in row["error"] or "HTTP 403" in row["error"]:
                            raise SystemExit(f"Juge indisponible : {row['error']}") from exc
                tokens = (row.get("tokens_in", 0), row.get("tokens_out", 0))
                row["cost_eur"] = (judge.row_cost(*tokens) if hasattr(judge, "row_cost")
                                   else token_cost_eur(judge.model, *tokens))
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            mark = {"correcte": "OK ", "partielle": "~  ", "incorrecte": "KO "}.get(
                row.get("verdict"), "ERR"
            )
            print(
                f"{mark} {row['id']:<7} exact {row.get('exactitude', '-')} fid {row.get('fidelite', '-')} "
                f"mots-clés {'OK' if row['keyword_correct'] else 'KO'}  {row.get('justification', row.get('error', ''))[:90]}",
                flush=True,
            )
            if args.pause:
                time.sleep(args.pause)

    summary = summarize(rows)
    summary |= {
        "answers_file": args.answers.name,
        "judge_backend": judge.name,
        "judge_model": judge.model,
        "judge_price": (vars(TOKEN_PRICES[judge.model]) if judge.model in TOKEN_PRICES else None),
        "rate_source": RATE_SOURCE,
        "seconds": round(time.perf_counter() - start, 1),
        "date": datetime.now().isoformat(timespec="seconds"),
    }
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nRésultats : {out}")
    for key in (
        "judged",
        "verdicts",
        "exactitude_mean",
        "fidelite_mean",
        "citation_rate",
        "agreement_keywords",
        "kappa_keywords",
        "disagreements",
        "cost_eur",
        "seconds",
    ):
        print(f"  {key:<20} {summary[key]}")

    if not args.no_mlflow:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment("judge")
        with mlflow.start_run(run_name=f"{slug}_{args.answers.stem}"):
            mlflow.log_params(
                {
                    "judge_backend": judge.name,
                    "judge_model": judge.model,
                    "answers_file": args.answers.name,
                    "n_answers": len(rows),
                }
            )
            mlflow.log_metrics(
                {
                    k: float(v)
                    for k, v in summary.items()
                    if isinstance(v, int | float) and not isinstance(v, bool)
                }
            )
            mlflow.log_artifact(str(out))


if __name__ == "__main__":
    main()
