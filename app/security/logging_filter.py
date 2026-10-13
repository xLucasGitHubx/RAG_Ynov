"""Filtre de journalisation : masque les données personnelles avant toute écriture.

Les questions ne sont déjà jamais journalisées ; ce filtre est une seconde barrière (messages
d'erreur de bibliothèques, exceptions contenant une saisie utilisateur...).
"""

import logging

from app.security.pii import mask_pii


class PIIMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # message mal formé : on le laisse tel quel
            return True
        masked = mask_pii(message)
        if masked != message:
            record.msg, record.args = masked, ()
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Ajoute le filtre à tous les handlers du logger racine (idempotent)."""
    for handler in (logger or logging.getLogger()).handlers:
        if not any(isinstance(f, PIIMaskingFilter) for f in handler.filters):
            handler.addFilter(PIIMaskingFilter())
