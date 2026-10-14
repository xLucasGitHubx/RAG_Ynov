"""Publie le dossier space/ sur le Space Hugging Face (LLM_SPACE_ID) et vérifie son état.

Lit HF_TOKEN et LLM_SPACE_ID dans .env (jamais affichés). Le Space doit exister et être réglé
sur le matériel ZeroGPU dans ses paramètres : ce script ne crée rien et ne change pas le matériel.

Usage :
    python -m scripts.deploy_space            # publie puis attend que le Space démarre
    python -m scripts.deploy_space --status   # affiche seulement l'état du Space
"""

import argparse
import sys
import time
from pathlib import Path

from huggingface_hub import HfApi

from app.config import get_settings

SPACE_DIR = Path(__file__).resolve().parents[1] / "space"
FILES = ["app.py", "requirements.txt", "README.md"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--status", action="store_true", help="affiche l'état sans publier")
    parser.add_argument("--timeout", type=int, default=900, help="attente du démarrage (s)")
    args = parser.parse_args()

    settings = get_settings()
    token = settings.hf_token.get_secret_value() if settings.hf_token else ""
    if not token or not settings.llm_space_id:
        sys.exit("HF_TOKEN et LLM_SPACE_ID doivent être renseignés dans .env.")
    api = HfApi(token=token)
    space = settings.llm_space_id
    print(f"Compte : {api.whoami()['name']} | Space : {space}")

    runtime = api.get_space_runtime(space)
    print(f"Matériel : {runtime.hardware or '?'} (demandé : {runtime.requested_hardware or '?'})")
    if "zero" not in str(runtime.requested_hardware or runtime.hardware or "").lower():
        print("Attention : le Space n'est pas sur ZeroGPU (Settings > Space hardware).")
    if args.status:
        print(f"État : {runtime.stage}")
        return

    commit = api.upload_folder(
        repo_id=space, repo_type="space", folder_path=SPACE_DIR, allow_patterns=FILES,
        commit_message="Mise à jour du Space rag-llm depuis le dépôt du projet",
    )
    print(f"Publié : {commit.commit_url}")

    deadline = time.monotonic() + args.timeout
    last = None
    while time.monotonic() < deadline:
        stage = api.get_space_runtime(space).stage
        if stage != last:
            print(f"  état : {stage}", flush=True)
            last = stage
        if stage == "RUNNING":
            print("Space prêt.")
            return
        if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
            sys.exit(f"Échec du Space ({stage}) : voir l'onglet Logs sur huggingface.co.")
        time.sleep(15)
    sys.exit("Délai dépassé : le Space n'a pas fini de démarrer.")


if __name__ == "__main__":
    main()
