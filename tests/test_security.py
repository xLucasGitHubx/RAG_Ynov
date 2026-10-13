"""Tests de sécurité : filtre RGPD, masquage des logs, clés d'API, rôles, limitation de débit."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.security.auth import parse_api_keys, rate_limiter
from app.security.logging_filter import PIIMaskingFilter
from app.security.pii import detect_pii, mask_pii
from eval.common import read_jsonl

EVAL_DIR = Path(__file__).parents[1] / "eval"
PII_MESSAGES = read_jsonl(EVAL_DIR / "pii_messages.jsonl")
QUESTIONS = read_jsonl(EVAL_DIR / "questions.jsonl")

client = TestClient(app)


@pytest.fixture
def api_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-employe:employe,cle-rh:admin")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("API_KEYS")
    get_settings.cache_clear()


# ----------------------------------------------------------------- filtre RGPD


@pytest.mark.parametrize("item", PII_MESSAGES, ids=[m["id"] for m in PII_MESSAGES])
def test_les_20_messages_faker_sont_detectes(item):
    kinds = {m.kind for m in detect_pii(item["message"])}
    assert item["type"] in kinds


@pytest.mark.parametrize("item", PII_MESSAGES[::4], ids=[m["id"] for m in PII_MESSAGES[::4]])
def test_l_api_bloque_les_questions_avec_donnees_personnelles(item, caplog):
    with caplog.at_level(logging.INFO):
        response = client.post("/ask", json={"question": item["message"]})
    assert response.status_code == 400
    assert "données personnelles" in response.json()["detail"]
    assert item["message"] not in caplog.text


def test_aucune_question_legitime_n_est_bloquee():
    faux_positifs = [q["question"] for q in QUESTIONS if detect_pii(q["question"])]
    assert faux_positifs == []


def test_les_chiffres_courants_ne_sont_pas_des_donnees_personnelles():
    for text in ("3 000 km avec 5 CV", "2,50 euros par jour", "article 15", "poste 4242",
                 "365 − 104 − 9 − 27 − 218 = 7", "le 01/03/2025 à 9 h 30"):
        assert detect_pii(text) == [], text


def test_un_iban_invalide_n_est_pas_detecte():
    assert detect_pii("FR76 3000 6000 0112 3456 7890 188") == []  # clé fausse


def test_mask_pii_remplace_par_le_type():
    text = "Écris à jean.dupont@exemple.fr ou au 06 12 34 56 78"
    assert mask_pii(text) == "Écris à [EMAIL] ou au [TELEPHONE]"


def test_le_filtre_de_logs_masque_les_donnees_personnelles():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "Contact : %s",
                               ("marie@exemple.fr",), None)
    PIIMaskingFilter().filter(record)
    assert record.getMessage() == "Contact : [EMAIL]"


# ----------------------------------------------------------------- authentification


def test_sans_api_keys_l_authentification_est_desactivee():
    assert client.post("/ask", json={"question": "Bonjour"}).status_code == 200


def test_cle_absente_ou_invalide_renvoie_401(api_keys):
    assert client.post("/ask", json={"question": "Bonjour"}).status_code == 401
    response = client.post("/ask", json={"question": "Bonjour"},
                           headers={"X-API-Key": "mauvaise"})
    assert response.status_code == 401


def test_cle_employe_peut_poser_une_question(api_keys):
    response = client.post("/ask", json={"question": "Bonjour"},
                           headers={"X-API-Key": "cle-employe"})
    assert response.status_code == 200


def test_ingest_est_reserve_aux_admins(api_keys):
    response = client.post("/ingest", headers={"X-API-Key": "cle-employe"})
    assert response.status_code == 403


def test_parse_api_keys_refuse_un_role_inconnu():
    assert parse_api_keys("a:admin, b") == {"a": "admin", "b": "employe"}
    with pytest.raises(ValueError):
        parse_api_keys("a:pirate")


def test_limitation_de_debit_renvoie_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    get_settings.cache_clear()
    rate_limiter.reset()
    try:
        codes = [client.post("/ask", json={"question": "Bonjour"}).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
    finally:
        monkeypatch.delenv("RATE_LIMIT_PER_MINUTE")
        get_settings.cache_clear()
        rate_limiter.reset()
