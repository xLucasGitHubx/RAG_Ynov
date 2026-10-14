"""Authentification par clé d'API (en-tête X-API-Key), rôles et limitation de débit.

Configuration : API_KEYS="cle-employe-1:employe,cle-rh:admin". Deux rôles :
- employe : poser des questions (/ask, /ask/stream, /feedback) ;
- admin   : idem + réindexer les documents (/ingest).

Si API_KEYS est vide, l'authentification est désactivée (développement local uniquement) :
un avertissement est journalisé au démarrage.
"""

import hashlib
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

logger = logging.getLogger("rag.security")

ROLES = ("employe", "admin")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False,
                              description="Clé d'API (rôle employe ou admin).")


@dataclass(frozen=True)
class Principal:
    key_id: str  # empreinte courte de la clé : jamais la clé elle-même dans les logs
    role: str


ANONYMOUS = Principal("anonyme", "admin")


def parse_api_keys(raw: str | None) -> dict[str, str]:
    keys: dict[str, str] = {}
    for item in (raw or "").split(","):
        if not item.strip():
            continue
        key, _, role = item.strip().partition(":")
        role = role.strip() or "employe"
        if role not in ROLES:
            raise ValueError(f"Rôle inconnu dans API_KEYS : {role}")
        keys[key.strip()] = role
    return keys


def key_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


class RateLimiter:
    """Fenêtre glissante d'une minute, en mémoire (suffisant pour une seule instance)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, identity: str, limit_per_minute: int) -> float | None:
        """Renvoie None si la requête est autorisée, sinon le délai d'attente en secondes."""
        if limit_per_minute <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            hits = self._hits[identity]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= limit_per_minute:
                return 60 - (now - hits[0])
            hits.append(now)
        return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def authenticate(
    api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    keys = parse_api_keys(settings.api_keys.get_secret_value() if settings.api_keys else None)
    if not keys:
        principal = ANONYMOUS
    elif not api_key or api_key not in keys:
        raise HTTPException(status_code=401, detail="Clé d'API absente ou invalide.",
                            headers={"WWW-Authenticate": "APIKey"})
    else:
        principal = Principal(key_id(api_key), keys[api_key])

    wait = rate_limiter.check(principal.key_id, settings.rate_limit_per_minute)
    if wait is not None:
        raise HTTPException(status_code=429,
                            detail="Trop de requêtes : réessayez dans quelques secondes.",
                            headers={"Retry-After": str(int(wait) + 1)})
    return principal


def require_admin(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Action réservée au rôle admin.")
    return principal
