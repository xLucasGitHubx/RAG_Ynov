"""Tests du juge LLM et du calcul des coûts (aucun appel à un modèle)."""

import pytest

from eval.costs import TOKEN_PRICES, from_usd, gpu_cost_eur, token_cost_eur
from eval.judge import (
    build_user_prompt,
    cohen_kappa,
    keyword_verdict,
    parse_verdict,
    summarize,
)


def test_parse_verdict_extrait_le_json_meme_entoure_de_texte():
    text = (
        'Voici mon avis : {"exactitude": 5, "fidelite": 4, "citation": "oui", '
        '"verdict": "Correcte", "justification": "Chiffre exact."} Merci.'
    )
    assert parse_verdict(text) == {
        "verdict": "correcte",
        "exactitude": 5,
        "fidelite": 4,
        "citation": True,
        "justification": "Chiffre exact.",
    }


@pytest.mark.parametrize(
    "text",
    [
        "pas de json",
        '{"exactitude": 7, "fidelite": 4, "citation": true, "verdict": "correcte"}',
        '{"exactitude": 4, "fidelite": 4, "citation": true, "verdict": "bof"}',
    ],
)
def test_parse_verdict_refuse_les_reponses_invalides(text):
    with pytest.raises(ValueError):
        parse_verdict(text)


def test_kappa_vaut_1_pour_un_accord_parfait_et_0_pour_le_hasard():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1
    assert cohen_kappa([True, True, False, False], [True, False, True, False]) == 0


def test_summarize_mesure_l_accord_avec_les_mots_cles_et_le_cout():
    rows = [
        {
            "id": "a",
            "type": "factuelle",
            "verdict": "correcte",
            "exactitude": 5,
            "fidelite": 5,
            "citation": True,
            "keyword_correct": True,
            "tokens_in": 1000,
            "tokens_out": 50,
            "cost_eur": 0.001,
        },
        {
            "id": "b",
            "type": "factuelle",
            "verdict": "partielle",
            "exactitude": 3,
            "fidelite": 5,
            "citation": True,
            "keyword_correct": True,
            "tokens_in": 1000,
            "tokens_out": 50,
            "cost_eur": 0.001,
        },
        {
            "id": "c",
            "type": "hors_perimetre",
            "verdict": "correcte",
            "exactitude": 5,
            "fidelite": 5,
            "citation": True,
            "keyword_correct": True,
            "tokens_in": 500,
            "tokens_out": 40,
            "cost_eur": 0.0005,
        },
        {"id": "d", "type": "factuelle", "keyword_correct": False, "error": "réponse non générée"},
    ]
    s = summarize(rows)
    assert s["judged"] == 3 and s["failed"] == 1
    assert s["verdicts"] == {"correcte": 2, "partielle": 1, "incorrecte": 0}
    assert s["exactitude_mean"] == 4  # moyenne sur les questions avec réponse attendue
    assert s["disagreements"] == ["b"]
    assert s["agreement_keywords"] == pytest.approx(2 / 3)
    assert s["cost_eur"] == pytest.approx(0.0025)


def test_build_user_prompt_contient_reference_extraits_et_reponse():
    row = {
        "question": "Combien ?",
        "answer": "Deux jours [doc.pdf].",
        "contexts": [
            {"document": "doc.pdf", "section": "Règle", "text": "Deux jours par semaine."}
        ],
    }
    prompt = build_user_prompt(row, {"answer": "2 jours"})
    assert "2 jours" in prompt and "Deux jours par semaine." in prompt and "[doc.pdf]" in prompt
    oos = build_user_prompt(
        {"question": "Météo ?", "answer": "Je ne sais pas.", "contexts": []}, {"answer": None}
    )
    assert "refuser" in oos and "aucun extrait" in oos


def test_couts_au_token_et_au_temps_gpu():
    # Ministral 3 8B : 0,1275 € par million de tokens, en entrée comme en sortie.
    assert token_cost_eur("ministral-8b-2512", 1_000_000, 0) == pytest.approx(0.1275)
    assert token_cost_eur("modele-inconnu", 10, 10) is None
    # ZeroGPU : 1 $ les 10 minutes, soit 0,10 $ la minute.
    assert gpu_cost_eur(60) == pytest.approx(from_usd(0.10))
    assert all(p.eur_per_m_input > 0 for p in TOKEN_PRICES.values())


def test_keyword_verdict_utilise_les_criteres_actuels():
    q = {"type": "factuelle", "keywords": ["^\\W*oui\\b", "six mois"]}
    assert keyword_verdict({"answer": "Oui, dès six mois.", "refused": False}, q) is True
    # Le mot-clé « six mois » seul ne suffit plus : la réponse « Non » est fausse.
    assert keyword_verdict({"answer": "Non, il faut six mois.", "refused": False}, q) is False
    assert keyword_verdict({"answer": None}, q) is False
    oos = {"type": "hors_perimetre"}
    assert keyword_verdict({"answer": "Je ne sais pas.", "refused": True}, oos) is True
