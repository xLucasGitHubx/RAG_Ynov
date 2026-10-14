"""L'empreinte d'un document ne dépend pas des fins de ligne (clone Windows ou Linux)."""

from ingestion.ingest import file_hash


def test_empreinte_identique_en_crlf_et_en_lf_pour_le_markdown(tmp_path):
    windows = tmp_path / "a.md"
    linux = tmp_path / "b.md"
    windows.write_bytes(b"# Titre\r\n\r\nTexte.\r\n")
    linux.write_bytes(b"# Titre\n\nTexte.\n")
    assert file_hash(windows) == file_hash(linux)


def test_empreinte_des_fichiers_binaires_inchangee(tmp_path):
    crlf = tmp_path / "a.pdf"
    lf = tmp_path / "b.pdf"
    crlf.write_bytes(b"%PDF\r\n")
    lf.write_bytes(b"%PDF\n")
    assert file_hash(crlf) != file_hash(lf)
