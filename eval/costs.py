"""Coût d'usage des LLM, en euros.

Prix relevés le 15/10/2026 sur les pages officielles. Les prix publiés en dollars sont convertis
au taux de référence de la Banque centrale européenne du 14/10/2026 : 1 € = 1,1195 $. Les tarifs
Mistral sont publiés directement en euros (docs.mistral.ai, bascule EUR).

Deux façons de payer un LLM :
- au token (API Mistral, fournisseurs d'inférence Hugging Face) : coût = tokens × prix ;
- au temps de GPU (ZeroGPU, GPU dédié) : coût = secondes de GPU × prix, que l'on rapporte à la
  réponse grâce au temps de génération mesuré dans le Space.
"""

from dataclasses import dataclass

USD_PER_EUR = 1.1195
RATE_SOURCE = "taux de référence BCE du 14/10/2026 (1 € = 1,1195 $)"


def from_usd(amount: float) -> float:
    return amount / USD_PER_EUR


@dataclass(frozen=True)
class TokenPrice:
    label: str
    eur_per_m_input: float  # € par million de tokens en entrée
    eur_per_m_output: float  # € par million de tokens en sortie
    source: str


TOKEN_PRICES: dict[str, TokenPrice] = {
    "ministral-8b-2512": TokenPrice(
        "API Mistral · Ministral 3 8B (le modèle de production)",
        0.1275,
        0.1275,
        "docs.mistral.ai, prix en euros, 15/10/2026",
    ),
    "mistral-small-2603": TokenPrice(
        "API Mistral · Mistral Small 4", 0.1275, 0.51, "docs.mistral.ai, prix en euros, 15/10/2026"
    ),
    "mistral-large-2512": TokenPrice(
        "API Mistral · Mistral Large 3", 0.425, 1.275, "docs.mistral.ai, prix en euros, 15/10/2026"
    ),
    "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra": TokenPrice(
        "Hugging Face · Qwen3 235B Instruct (DeepInfra)",
        from_usd(0.09),
        from_usd(0.55),
        "router.huggingface.co, 0,09 $ / 0,55 $ par million, 15/10/2026",
    ),
}

# Facturation au temps de GPU (prix publiés en dollars, convertis).
ZEROGPU_EUR_PER_SECOND = from_usd(0.10) / 60  # 1 $ pour 10 minutes au-delà du quota
L4_EUR_PER_HOUR = from_usd(0.80)  # 1x L4 24 Go dédiée
L40S_EUR_PER_HOUR = from_usd(1.80)  # 1x L40S 48 Go dédiée
T4_EUR_PER_HOUR = from_usd(0.40)  # 1x T4 16 Go (modèle en nf4)


def token_cost_eur(model: str, tokens_in: float, tokens_out: float) -> float | None:
    price = TOKEN_PRICES.get(model)
    if price is None:
        return None
    return (tokens_in * price.eur_per_m_input + tokens_out * price.eur_per_m_output) / 1e6


def gpu_cost_eur(seconds: float, eur_per_second: float = ZEROGPU_EUR_PER_SECOND) -> float:
    return seconds * eur_per_second
