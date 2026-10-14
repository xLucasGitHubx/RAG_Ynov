"""Estimation du coût mensuel pour N utilisateurs (itération 9).

Toutes les hypothèses sont des paramètres : le temps GPU par réponse vient de la mesure sur
ZeroGPU (eval/results/zerogpu_*.jsonl, champ generation_seconds), les prix des pages
officielles (relevés le 14/10/2026, voir docs/estimation_budget.md).

Usage :
    python -m scripts.finops                         # hypothèses par défaut
    python -m scripts.finops --gpu-seconds 6.2 --users 1000 --questions 3
"""

import argparse
import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"

# Prix (USD) relevés le 14/10/2026
ZEROGPU_USD_PER_MINUTE = 0.10        # 1 $ pour 10 minutes au-delà du quota
ZEROGPU_INCLUDED_MINUTES = 40        # par jour, compte PRO ou membre d'une org Team
HF_PRO_USD_PER_MONTH = 9.0
L4_USD_PER_HOUR = 0.80               # Inference Endpoint / Space, 1x L4 24 Go
L40S_USD_PER_HOUR = 1.80             # 1x L40S 48 Go
ACA_VCPU_SECOND = 0.000024           # Azure Container Apps, consommation, actif
ACA_GIB_SECOND = 0.000003
ACA_FREE_VCPU_SECONDS = 180_000      # par mois et par abonnement
ACA_FREE_GIB_SECONDS = 360_000
ACA_REQUESTS_PER_MILLION = 0.40
ACA_FREE_REQUESTS = 2_000_000
ACR_BASIC_USD_PER_DAY = 0.167


def measured_gpu_seconds() -> float | None:
    """Médiane des durées de génération mesurées sur ZeroGPU, si une évaluation existe."""
    values = []
    for path in RESULTS.glob("answers_zerogpu_*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            seconds = (row.get("llm_meta") or {}).get("generation_seconds")
            if seconds:
                values.append(seconds)
    return statistics.median(values) if values else None


def estimate(users: int, questions: float, gpu_seconds: float, llm_share: float,
             days: int, hours: float, vcpu: float, memory_gib: float) -> dict:
    asked = users * questions                       # questions par jour
    llm_calls = asked * llm_share                   # refus anticipés et blocages RGPD exclus
    gpu_minutes_day = llm_calls * gpu_seconds / 60

    zerogpu_extra = max(0.0, gpu_minutes_day - ZEROGPU_INCLUDED_MINUTES)
    zerogpu_month = zerogpu_extra * ZEROGPU_USD_PER_MINUTE * days + HF_PRO_USD_PER_MONTH

    # GPU dédié allumé pendant les heures ouvrées (mise à l'échelle à zéro la nuit).
    busy_hours_needed = gpu_minutes_day / 60
    l4_month = L4_USD_PER_HOUR * hours * days
    l40s_month = L40S_USD_PER_HOUR * hours * days

    # API : une réplique active pendant les heures ouvrées.
    seconds = hours * 3600 * days
    vcpu_cost = max(0.0, vcpu * seconds - ACA_FREE_VCPU_SECONDS) * ACA_VCPU_SECOND
    mem_cost = max(0.0, memory_gib * seconds - ACA_FREE_GIB_SECONDS) * ACA_GIB_SECOND
    req_cost = max(0.0, asked * days - ACA_FREE_REQUESTS) / 1e6 * ACA_REQUESTS_PER_MILLION
    api_month = vcpu_cost + mem_cost + req_cost + ACR_BASIC_USD_PER_DAY * 30

    return {
        "questions_per_day": asked,
        "llm_calls_per_day": llm_calls,
        "gpu_minutes_per_day": gpu_minutes_day,
        "gpu_busy_share": busy_hours_needed / hours,
        "zerogpu_month": zerogpu_month,
        "l4_month": l4_month,
        "l40s_month": l40s_month,
        "api_month": api_month,
        "api_detail": {"vcpu": vcpu_cost, "memory": mem_cost, "requests": req_cost,
                       "registry": ACR_BASIC_USD_PER_DAY * 30},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--questions", type=float, default=3, help="par utilisateur et par jour")
    parser.add_argument("--gpu-seconds", type=float, help="par réponse (défaut : mesure ZeroGPU)")
    parser.add_argument("--llm-share", type=float, default=0.95,
                        help="part des questions qui appellent le LLM")
    parser.add_argument("--days", type=int, default=22, help="jours ouvrés par mois")
    parser.add_argument("--hours", type=float, default=10, help="heures d'activité par jour")
    parser.add_argument("--vcpu", type=float, default=2)
    parser.add_argument("--memory", type=float, default=4, help="Go de mémoire de l'API")
    args = parser.parse_args()

    measured = measured_gpu_seconds()
    gpu = args.gpu_seconds or measured or 8.0
    source = ("argument" if args.gpu_seconds
              else "mesure ZeroGPU" if measured else "hypothèse du plan")
    r = estimate(args.users, args.questions, gpu, args.llm_share, args.days, args.hours,
                 args.vcpu, args.memory)
    print(f"{args.users} utilisateurs × {args.questions} questions/jour, {args.days} jours ouvrés")
    print(f"Temps GPU par réponse : {gpu:.2f} s ({source})")
    print(f"Appels au LLM : {r['llm_calls_per_day']:.0f}/jour -> "
          f"{r['gpu_minutes_per_day']:.0f} min GPU/jour "
          f"(GPU occupé {r['gpu_busy_share']:.0%} des heures ouvrées)")
    print(f"ZeroGPU (40 min incluses + crédits + PRO) : {r['zerogpu_month']:.0f} $/mois")
    print(f"GPU dédié L4, {args.hours:.0f} h/jour        : {r['l4_month']:.0f} $/mois")
    print(f"GPU dédié L40S, {args.hours:.0f} h/jour      : {r['l40s_month']:.0f} $/mois")
    print(f"API Azure Container Apps + registre    : {r['api_month']:.0f} $/mois "
          f"({', '.join(f'{k} {v:.1f}' for k, v in r['api_detail'].items())})")


if __name__ == "__main__":
    main()
