"""Tests de l'ajout et du retrait de documents depuis l'interface (rôle admin).

Ni Docling ni BGE-M3 : l'ingestion est remplacée par une fausse, qui « indexe » chaque document
présent dans data/raw sous forme de deux chunks dans une fausse collection.
"""

import json
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

import app.admin as admin
import app.documents as documents
from app.config import get_settings
from app.documents import DocumentError, safe_filename
from app.main import app

client = TestClient(app)


class FakeCollection:
    def __init__(self) -> None:
        self.chunks: dict[str, str] = {}  # id -> document

    def get(self, where=None, include=None):
        doc = (where or {}).get("document")
        return {"ids": [i for i, d in self.chunks.items() if doc is None or d == doc]}

    def delete(self, where=None):
        doc = (where or {}).get("document")
        self.chunks = {i: d for i, d in self.chunks.items() if d != doc}


class FakeRetriever:
    def __init__(self) -> None:
        self.collection = FakeCollection()
        self.embedder = object()
        self.refreshed = 0

    def refresh_lexical(self) -> None:
        self.refreshed += 1


@dataclass
class FakeReport:
    seconds: float = 0.2


def fake_ingest(settings, retriever, name):
    retriever.collection.chunks = {}
    for path in settings.raw_dir.iterdir():
        if path.name != "metadata.json":
            for i in range(2):
                retriever.collection.chunks[f"{path.name}::{i}"] = path.name
    return FakeReport()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """data/raw temporaire avec un document du corpus de référence."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "charte.md").write_text("# Charte\n\nRègles.", encoding="utf-8")
    (raw / "metadata.json").write_text(json.dumps({"charte.md": {"titre": "Charte"}}),
                                       encoding="utf-8")
    monkeypatch.setenv("RAW_DIR", str(raw))
    get_settings.cache_clear()
    retriever = FakeRetriever()
    monkeypatch.setattr(admin, "_retriever", lambda: retriever)
    monkeypatch.setattr(documents, "_run_ingest", fake_ingest)
    yield raw, retriever
    get_settings.cache_clear()


def envoyer(nom="Procédure VPN.md", contenu=b"# VPN\n\nSe connecter.", **champs):
    data = {"titre": "Procédure VPN", "categorie": "IT", **champs}
    return client.post("/api/admin/documents", data=data,
                       files={"fichier": (nom, contenu, "text/markdown")})


def test_safe_filename_retire_chemin_accents_et_espaces():
    assert safe_filename("../../Procédure VPN (v2).MD") == "procedure_vpn_v2.md"
    assert safe_filename("C:\\dossier\\Guide.docx") == "guide.docx"
    with pytest.raises(DocumentError) as exc:
        safe_filename("script.exe")
    assert exc.value.status_code == 415
    with pytest.raises(DocumentError):
        safe_filename("sans_extension")


def test_ajout_reserve_au_role_admin(corpus, monkeypatch):
    monkeypatch.setenv("API_KEYS", "cle-employe:employe,cle-admin:admin")
    get_settings.cache_clear()
    assert envoyer().status_code == 401
    refus = client.post("/api/admin/documents", headers={"X-API-Key": "cle-employe"},
                        data={"titre": "Procédure VPN"},
                        files={"fichier": ("vpn.md", b"# VPN", "text/markdown")})
    assert refus.status_code == 403
    ok = client.post("/api/admin/documents", headers={"X-API-Key": "cle-admin"},
                     data={"titre": "Procédure VPN"},
                     files={"fichier": ("vpn.md", b"# VPN", "text/markdown")})
    assert ok.status_code == 201


def test_ajout_enregistre_le_fichier_les_metadonnees_et_indexe(corpus):
    raw, retriever = corpus
    response = envoyer(version="2026", date_effet="2026-10-01")
    assert response.status_code == 201
    body = response.json()
    assert body == {"document": "procedure_vpn.md", "format": "md", "chunks": 2, "seconds": 0.2}
    assert (raw / "procedure_vpn.md").read_bytes() == b"# VPN\n\nSe connecter."
    meta = json.loads((raw / "metadata.json").read_text(encoding="utf-8"))["procedure_vpn.md"]
    assert meta["origine"] == "interface"
    assert meta["categorie"] == "IT" and meta["date_effet"] == "2026-10-01"
    assert retriever.refreshed == 1
    listed = {d["document"]: d for d in client.get("/api/documents").json()}
    assert listed["procedure_vpn.md"]["origine"] == "interface"
    assert listed["charte.md"]["origine"] == "corpus"


def test_ajout_refuse_les_formats_non_pris_en_charge(corpus):
    assert envoyer(nom="macro.xlsm").status_code == 415


def test_ajout_refuse_d_ecraser_le_corpus_de_reference(corpus):
    response = envoyer(nom="Charte.md", remplacer="true")
    assert response.status_code == 409
    assert "corpus de référence" in response.json()["detail"]


def test_ajout_en_double_demande_remplacer(corpus):
    assert envoyer().status_code == 201
    assert envoyer().status_code == 409
    assert envoyer(contenu=b"# VPN v2", remplacer="true").status_code == 201


def test_echec_d_indexation_annule_tout(corpus, monkeypatch):
    raw, retriever = corpus
    before = json.loads((raw / "metadata.json").read_text(encoding="utf-8"))

    def broken(settings, retriever, name):
        raise ValueError("PDF illisible")

    monkeypatch.setattr(documents, "_run_ingest", broken)
    response = envoyer()
    assert response.status_code == 422
    assert "PDF illisible" in response.json()["detail"]
    assert not (raw / "procedure_vpn.md").exists()
    assert json.loads((raw / "metadata.json").read_text(encoding="utf-8")) == before


def test_retrait_limite_aux_documents_ajoutes_depuis_l_interface(corpus):
    raw, retriever = corpus
    assert client.delete("/api/admin/documents/charte.md").status_code == 403
    assert client.delete("/api/admin/documents/inconnu.md").status_code == 404
    envoyer()
    assert client.delete("/api/admin/documents/procedure_vpn.md").status_code == 204
    assert not (raw / "procedure_vpn.md").exists()
    assert "procedure_vpn.md" not in json.loads((raw / "metadata.json").read_text("utf-8"))
    assert retriever.collection.get(where={"document": "procedure_vpn.md"})["ids"] == []


def test_whoami_indique_le_role_et_les_capacites():
    body = client.get("/api/whoami").json()
    assert body["role"] == "admin"  # authentification désactivée en local
    assert body["auth_enabled"] is False
    assert body["upload"]["max_mb"] == get_settings().upload_max_mb


def test_pdf_sans_couche_texte_detecte_comme_scan(tmp_path):
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842)
    path = tmp_path / "scan.pdf"
    pdf.save(path)
    assert documents.is_scanned_pdf(path) is True
