"""Configuration commune des tests : aucun test n'appelle un vrai LLM ni ne charge de modèle."""

import os

# Forcé avant l'import de l'application : les tests tournent sans clé, sans réseau et sans index.
os.environ["LLM_PROVIDER"] = "static"
os.environ["RAG_ENABLED"] = "false"
os.environ.pop("MISTRAL_API_KEY", None)
os.environ["API_KEYS"] = ""  # authentification désactivée par défaut dans les tests
os.environ["MLFLOW_TRACKING_ENABLED"] = "false"


import pytest  # noqa: E402

from app.security.auth import rate_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Chaque test repart d'un compteur vide (sinon la limite par minute serait atteinte)."""
    rate_limiter.reset()
    yield
