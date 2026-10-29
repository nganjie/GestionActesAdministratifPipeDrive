"""Journalisation structurée avec identifiant de corrélation (RG08, FRS RI09)."""

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SECRET_PATTERNS = [
    re.compile(r"(x-api-token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+", re.IGNORECASE),
    re.compile(r"(api_token=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(bearer\s+)[A-Za-z0-9\-_.]+", re.IGNORECASE),
]


def nouvel_identifiant_correlation() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def masquer_secrets(texte: str) -> str:
    for motif in _SECRET_PATTERNS:
        texte = motif.sub(r"\1***", texte)
    return texte


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entree = {
            "date": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "logger": record.name,
            "message": masquer_secrets(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
        }
        for cle in ("operation", "resultat", "code_erreur", "duree_ms", "tentative"):
            if hasattr(record, cle):
                entree[cle] = getattr(record, cle)
        if record.exc_info:
            entree["exception"] = masquer_secrets(self.formatException(record.exc_info))
        return json.dumps(entree, ensure_ascii=False)


def configurer_logging(niveau: str = "INFO") -> None:
    racine = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in racine.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    racine.handlers = [handler]
    racine.setLevel(niveau)
    logging.getLogger("httpx").setLevel(logging.WARNING)
