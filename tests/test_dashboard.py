"""Tests des routes de l'interface (/api) et du service des fichiers de /ui."""

import json

import pytest
from fastapi.testclient import TestClient

import app.dashboard as dashboard
import app.main as main
from app.config import get_settings
from app.dashboard import summarize_runs
from app.main import app

client = TestClient(app)


@pytest.fixture
def api_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-employe:employe")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_config_expose_la_configuration_sans_secret(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "secret-a-ne-pas-montrer")
    get_settings.cache_clear()
    try:
        body = client.get("/api/config").json()
    finally:
        get_settings.cache_clear()
    assert body["llm"]["provider"] == "static"
    assert body["chunking"]["size"] == get_settings().chunk_size
    assert body["security"]["auth_enabled"] is False
    assert "secret-a-ne-pas-montrer" not in json.dumps(body)


def test_les_routes_de_l_interface_exigent_la_cle_d_api(api_keys):
    assert client.get("/api/config").status_code == 401
    ok = client.get("/api/config", headers={"X-API-Key": "cle-employe"})
    assert ok.status_code == 200


def test_documents_sans_recherche_renvoie_les_metadonnees_sans_statistiques():
    rows = client.get("/api/documents").json()
    assert any(r["document"] == "accord_teletravail_2025.docx" for r in rows)
    assert all(r["chunks"] is None for r in rows)  # RAG désactivé dans les tests
    obsolete = [r["document"] for r in rows if r["statut"] == "obsolete"]
    assert obsolete == ["accord_teletravail_2023.docx"]


def test_chunks_indisponibles_sans_recherche():
    assert client.get("/api/documents/x.pdf/chunks").status_code == 409


def test_reports_lit_le_fichier_genere(tmp_path, monkeypatch):
    report = tmp_path / "dashboard.json"
    report.write_text(json.dumps({"generated_at": "2026-10-14"}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "REPORT_FILE", report)
    assert client.get("/api/reports").json() == {"generated_at": "2026-10-14"}
    monkeypatch.setattr(dashboard, "REPORT_FILE", tmp_path / "absent.json")
    assert client.get("/api/reports").status_code == 404


def test_monitoring_desactive_dans_les_tests():
    assert client.get("/api/monitoring").json()["available"] is False


def test_summarize_runs_agrege_les_latences_les_statuts_et_le_feedback():
    def run(status, total, llm=None, refused=0, feedback=None):
        metrics = {"latency_total_ms": total, "refused": refused, "llm_called": int(bool(llm))}
        if llm:
            metrics["latency_llm_ms"] = llm
        return {"request_id": "a" * 32, "time": 0, "endpoint": "ask", "status": status,
                "metrics": metrics, "feedback": feedback}

    summary = summarize_runs([
        run("ok", 100, 80, feedback=1), run("ok", 300, 250), run("ok", 50, refused=1,
                                                                 feedback=-1),
        run("bloquee_rgpd", 0),
    ])
    assert summary["total"] == 4
    assert summary["statuses"] == {"ok": 3, "bloquee_rgpd": 1}
    assert summary["latency"]["total"]["p50"] == 100
    assert summary["latency"]["llm"]["count"] == 2
    assert summary["refusal_rate"] == pytest.approx(1 / 3)
    assert summary["feedback"] == {"positive": 1, "negative": 1}
    assert summary["recent"][0]["request_id"] == "a" * 8


def test_ui_sert_index_html_pour_toutes_les_routes(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(main, "UI_DIR", tmp_path)
    assert client.get("/ui/evaluation").text == "<html>ui</html>"
    assert client.get("/ui/assets/app.js").text == "console.log(1)"
    # Pas de sortie du dossier de l'interface.
    assert client.get("/ui/..%2F..%2Fapp%2Fconfig.py").text == "<html>ui</html>"
    assert client.get("/", follow_redirects=False).headers["location"] == "/ui/"
