"""Tests du suivi des requêtes et du feedback (faux tracker en mémoire, MLflow non utilisé)."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.monitoring.tracker import FeedbackRecord, RequestRecord, Tracker

client = TestClient(app)


class MemoryTracker(Tracker):
    def __init__(self):
        self.requests: list[RequestRecord] = []
        self.feedbacks: list[FeedbackRecord] = []

    def track(self, record):
        self.requests.append(record)

    def feedback(self, record):
        self.feedbacks.append(record)


@pytest.fixture
def tracker(monkeypatch):
    memory = MemoryTracker()
    monkeypatch.setattr(main, "get_tracker", lambda: memory)
    return memory


def test_chaque_question_est_suivie_sans_son_contenu(tracker):
    question = "Combien de jours de congés ai-je ?"
    response = client.post("/ask", json={"question": question})
    body = response.json()
    assert len(body["request_id"]) == 32
    assert response.headers["x-request-id"] == body["request_id"]

    record = tracker.requests[0]
    assert record.request_id == body["request_id"]
    assert record.metrics["question_chars"] == len(question)
    assert "latency_total_ms" in record.metrics
    assert record.params["llm_provider"] == "static"
    everything = str(record.params) + str(record.metrics) + str(record.tags)
    assert question not in everything


def test_une_question_bloquee_est_suivie_avec_son_statut(tracker):
    client.post("/ask", json={"question": "Mon mail est jean@exemple.fr"})
    assert tracker.requests[0].tags["status"] == "bloquee_rgpd"


def test_feedback_relie_a_la_requete(tracker):
    request_id = client.post("/ask", json={"question": "Bonjour"}).json()["request_id"]
    response = client.post("/feedback", json={"request_id": request_id, "rating": -1,
                                              "commentaire": "Réponse incomplète"})
    assert response.status_code == 202
    assert tracker.feedbacks[0] == FeedbackRecord(request_id, -1, len("Réponse incomplète"))


def test_feedback_refuse_un_identifiant_ou_une_note_invalide(tracker):
    assert client.post("/feedback", json={"request_id": "x'; DROP", "rating": 1}).status_code == 422
    assert client.post("/feedback", json={"request_id": "a" * 32, "rating": 5}).status_code == 422
