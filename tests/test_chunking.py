"""Tests du découpage (compteur de tokens simplifié : un mot = un token)."""

from ingestion.chunking import ChunkingConfig, chunk_markdown, split_sections
from ingestion.parsing import relevel_headings


def count(text: str) -> int:
    return len(text.split())


def words(n: int, prefix: str = "mot") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


DOC = f"""# Accord télétravail

## Article 1 — Définitions

{words(30, "def")}

## Article 2 — Éligibilité

{words(150, "elig")}

## Article 3 — Indemnité

Les montants sont les suivants :

| Cas | Montant |
| --- | --- |
| Jour | 2,50 € |
| Mois | 55 € |
"""


def test_les_sections_suivent_les_titres():
    sections = split_sections(DOC)
    assert [s.path[-1] for s in sections] == [
        "Article 1 — Définitions", "Article 2 — Éligibilité", "Article 3 — Indemnité",
    ]
    assert sections[0].path == ["Accord télétravail", "Article 1 — Définitions"]


def test_chaque_chunk_est_prefixe_par_son_chemin():
    chunks = chunk_markdown(DOC, "Accord télétravail 2025", ChunkingConfig(512, 0, 0), count)
    assert chunks[0].text.startswith("Accord télétravail 2025 > Article 1 — Définitions\n\n")
    # Le titre « # » du fichier est remplacé par le titre officiel, pas répété.
    assert "Accord télétravail > " not in chunks[0].text


def test_une_section_trop_longue_est_redecoupee():
    chunks = chunk_markdown(DOC, "Accord", ChunkingConfig(64, 0, 0), count)
    eligibilite = [c for c in chunks if c.section.endswith("Éligibilité")]
    assert len(eligibilite) >= 3
    assert all(c.n_tokens <= 64 for c in eligibilite)


def test_un_tableau_n_est_jamais_coupe_et_garde_son_introduction():
    chunks = chunk_markdown(DOC, "Accord", ChunkingConfig(10, 0, 0), count)
    table_chunks = [c for c in chunks if "| Jour" in c.body]
    assert len(table_chunks) == 1
    assert "| Mois" in table_chunks[0].body
    assert "Les montants sont les suivants" in table_chunks[0].body


def test_les_petits_fragments_sont_fusionnes_avec_une_section_soeur():
    chunks = chunk_markdown(DOC, "Accord", ChunkingConfig(512, 0, 100), count)
    first = chunks[0]
    assert "def0" in first.body and "elig0" in first.body
    assert first.section == "Accord"  # chemin remonté au parent commun
    assert "### Article 1 — Définitions" in first.body
    # L'article 3 (petit tableau) rejoint aussi ce chunk : les 3 sections sont tracées.
    assert len(first.sections) == 3
    assert "### Article 3 — Indemnité" in first.body and "| Mois" in first.body


def test_mode_par_section_un_chunk_par_section():
    chunks = chunk_markdown(DOC, "Accord", ChunkingConfig(None, 0, 0), count)
    assert len(chunks) == 3


def test_le_numero_de_page_suit_les_marqueurs():
    md = (
        "<!-- page: 1 -->\n\n## Article 1\n\nTexte page un.\n\n"
        "<!-- page: 2 -->\n\nSuite page deux.\n\n## Article 2\n\nTexte page deux."
    )
    chunks = chunk_markdown(md, "Doc", ChunkingConfig(3, 0, 0), count)
    assert chunks[0].page == 1
    assert any(c.page == 2 and "Suite" in c.body for c in chunks)
    assert chunks[-1].page == 2
    assert all("<!--" not in c.text for c in chunks)


def test_relevel_reconstruit_la_hierarchie_des_titres_pdf():
    md = "## Guide des congés\n\n## 1. Les congés payés\n\n## 1.1 Nombre de jours\n\n## Contacts"
    lines = relevel_headings(md).splitlines()
    assert lines[0] == "# Guide des congés"
    assert lines[2] == "## 1. Les congés payés"
    assert lines[4] == "### 1.1 Nombre de jours"


def test_relevel_ne_touche_pas_une_hierarchie_existante():
    md = "# Titre\n\n## Section\n\n### Sous-section"
    assert relevel_headings(md) == md
