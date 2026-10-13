"""Choix du fournisseur de LLM selon la configuration (variable LLM_PROVIDER)."""

from app.config import Settings
from app.llm.base import LLMClient, LLMNotConfiguredError
from app.llm.static_client import StaticClient


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "static":
        return StaticClient(settings.static_answer)

    if settings.llm_provider == "ollama":
        from app.llm.ollama_client import OllamaClient

        return OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout_s=settings.llm_timeout_s,
            num_ctx=settings.ollama_num_ctx,
        )

    if settings.llm_provider == "zerogpu":
        token = settings.hf_token.get_secret_value() if settings.hf_token else ""
        if not token or not settings.llm_space_id:
            raise LLMNotConfiguredError(
                "HF_TOKEN et LLM_SPACE_ID sont requis pour LLM_PROVIDER=zerogpu."
            )
        from app.llm.zerogpu_client import ZeroGPUClient

        return ZeroGPUClient(settings.llm_space_id, token)

    if settings.llm_provider == "mistral":
        if settings.mistral_api_key is None or not settings.mistral_api_key.get_secret_value():
            raise LLMNotConfiguredError(
                "MISTRAL_API_KEY est absente : ajoute-la dans le fichier .env "
                "ou passe LLM_PROVIDER=static."
            )
        from app.llm.mistral_client import MistralClient  # import tardif : SDK chargé si utilisé

        return MistralClient(
            api_key=settings.mistral_api_key.get_secret_value(),
            model=settings.mistral_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout_s=settings.llm_timeout_s,
        )

    raise LLMNotConfiguredError(f"Fournisseur de LLM inconnu : {settings.llm_provider}")
