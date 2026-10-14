"""Configuration de l'application, lue depuis les variables d'environnement ou le fichier .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Assistant RH/IT — Nexalis Conseil"
    environment: str = "local"
    # Commit déployé, posé par le workflow de déploiement (vide en local).
    git_sha: str = ""
    log_level: str = "INFO"

    # --- LLM ---
    # "ollama"  : modèle local quantifié (développement, zéro minute GPU ZeroGPU)
    # "mistral" : API Mistral (provisoire, avant le modèle auto-hébergé)
    # "static"  : réponse fixe, sans appel externe (tests, démo hors ligne)
    # "zerogpu" : Space Gradio ZeroGPU sur Hugging Face (production, itération 4 bis)
    llm_provider: Literal["ollama", "zerogpu", "mistral", "static"] = "ollama"
    mistral_api_key: SecretStr | None = None
    mistral_model: str = "mistral-small-latest"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "ministral-3:3b"
    ollama_num_ctx: int = 4096  # prompt RAG ~1 600 tokens + 600 en sortie : 4k suffit
    hf_token: SecretStr | None = None
    llm_space_id: str | None = None
    llm_temperature: float = 0.1
    llm_max_tokens: int = 600
    llm_timeout_s: int = 120

    # Réponse du fournisseur "static"
    static_answer: str = "Bonjour, je suis l'assistant RH"

    # --- Recherche (RAG) ---
    # Désactivable pour les tests et pour démarrer l'API sans index ni modèle d'embeddings.
    rag_enabled: bool = True
    chroma_dir: Path = ROOT_DIR / "chroma_db"
    chroma_collection: str = "nexalis"
    embedding_model: str = "BAAI/bge-m3"
    embedding_max_length: int = 2048
    # Reranker désactivé par défaut : la recherche hybride fait mieux sans coût (voir
    # docs/resultats_retrieval.md). bge-reranker-v2-m3 prend ~13 s par question sur CPU.
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_enabled: bool = False
    # Nombre de chunks récupérés par la recherche vectorielle, puis gardés après reranking.
    retrieval_fetch_k: int = 20
    retrieval_top_k: int = 5
    # Score minimal du reranker (0 à 1) pour qu'un chunk soit envoyé au LLM.
    rerank_min_score: float = 0.05
    # Recherche hybride : BM25 (mots exacts) fusionné avec la recherche vectorielle (RRF).
    hybrid_search: bool = True
    # Poids du classement BM25 dans la fusion (1 = autant que la recherche vectorielle).
    hybrid_lexical_weight: float = 1.0
    # Seuil de similarité cosinus du meilleur chunk sous lequel on refuse sans appeler le LLM
    # (choisi par eval/analyze_gating.py : 0 question légitime écartée sur 58).
    retrieval_min_score: float = 0.42
    # Exclut les documents marqués "obsolete" dans data/raw/metadata.json.
    exclude_obsolete: bool = True

    # --- Sécurité ---
    # "cle1:employe,cle2:admin" ; vide = authentification désactivée (local uniquement).
    api_keys: SecretStr | None = None
    rate_limit_per_minute: int = 30
    # Bloque les questions contenant des données personnelles (NIR, IBAN, carte, e-mail, tél.).
    pii_filter_enabled: bool = True
    # Taille maximale d'un document ajouté depuis l'interface (rôle admin).
    upload_max_mb: int = 20

    # --- Suivi MLflow (itération 8) ---
    mlflow_tracking_enabled: bool = True
    mlflow_tracking_uri: str = f"sqlite:///{(ROOT_DIR / 'mlflow.db').as_posix()}"

    # --- Ingestion ---
    raw_dir: Path = ROOT_DIR / "data" / "raw"
    chunk_size: int = 256  # choisi par eval/eval_retrieval.py (voir docs/resultats_retrieval.md)
    chunk_overlap: int = 25
    chunk_min_tokens: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
