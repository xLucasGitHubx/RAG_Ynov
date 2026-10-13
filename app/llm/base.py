"""Interface commune à tous les fournisseurs de LLM.

Fournisseurs : Ollama en local (développement), Space ZeroGPU (production), API Mistral
(provisoire) et « static » (tests). Le reste de l'application ne connaît que cette interface.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Le fournisseur de LLM n'a pas pu produire de réponse."""


class LLMNotConfiguredError(LLMError):
    """Le fournisseur est choisi mais sa configuration est incomplète (clé manquante...)."""


@dataclass
class Generation:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    name: str
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        """Renvoie le texte généré pour un prompt système et un message utilisateur."""
        ...

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Renvoie le texte généré morceau par morceau (streaming)."""
        ...
