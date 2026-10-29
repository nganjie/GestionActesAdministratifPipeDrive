"""Client HTTP Pipedrive : authentification, délais, classification des erreurs, journalisation (ISD §3-§4)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_correlation_id
from app.integrations.pipedrive.errors import (
    ErreurDefinitive,
    ErreurIndeterminee,
    ErreurRelancable,
    NonConfigure,
    RessourceAbsente,
)

logger = logging.getLogger("app.pipedrive")
# httpx journalise l'URL complète au niveau INFO : les termes de recherche (e-mail, téléphone) y figureraient.
for _nom in ("httpx", "httpcore"):
    logging.getLogger(_nom).setLevel(logging.WARNING)

USER_AGENT = "actes-api/1.0"
_CODES_DEFINITIFS = {
    400: "REQUETE_INVALIDE",
    401: "AUTHENTIFICATION_REFUSEE",
    402: "PAIEMENT_REQUIS",
    403: "ACCES_INTERDIT",
    410: "ROUTE_RETIREE",
    422: "DONNEES_NON_TRAITABLES",
}


@dataclass
class AppelPipedrive:
    """Trace d'un appel, sans jeton ni corps (ISD §7.4)."""

    operation: str
    methode: str
    route: str
    statut: int | None
    duree_ms: int
    resultat: str
    code_erreur: str | None
    correlation_id: str | None


def _retry_after(reponse: httpx.Response) -> float | None:
    for entete in ("retry-after", "x-ratelimit-reset"):
        valeur = reponse.headers.get(entete)
        if not valeur:
            continue
        try:
            return max(0.0, float(valeur))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(valeur).timestamp() - time.time())
            except (TypeError, ValueError):
                continue
    return None


def _message_pipedrive(reponse: httpx.Response) -> str:
    try:
        corps = reponse.json()
    except ValueError:
        return reponse.reason_phrase or "réponse non JSON"
    message = corps.get("error") or corps.get("message") or reponse.reason_phrase
    return str(message)[:200]


class PipedriveClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None,
                 on_appel: Callable[[AppelPipedrive], None] | None = None):
        self._settings = settings
        self._http = http or httpx.AsyncClient(
            base_url=settings.pipedrive_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.pipedrive_read_timeout, connect=settings.pipedrive_connect_timeout),
        )
        self._possede_http = http is None
        self.on_appel = on_appel

    async def aclose(self) -> None:
        if self._possede_http:
            await self._http.aclose()

    async def requete(self, operation: str, methode: str, route: str, *, chemin: str | None = None,
                      params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """Exécute un appel. `route` est la forme journalisée (identifiants génériques), `chemin` l'URL réelle."""
        if not self._settings.pipedrive_configure:
            raise NonConfigure()
        assert self._settings.pipedrive_api_token is not None
        entetes = {
            "x-api-token": self._settings.pipedrive_api_token.get_secret_value(),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        debut = time.perf_counter()
        statut: int | None = None
        try:
            reponse = await self._http.request(methode, chemin or route, params=params, json=json, headers=entetes)
            statut = reponse.status_code
            corps = self._interpreter(reponse)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            erreur = ErreurIndeterminee("DELAI_DEPASSE" if isinstance(exc, httpx.TimeoutException)
                                        else "ERREUR_RESEAU", type(exc).__name__)
            self._tracer(operation, methode, route, None, debut, "ECHEC", erreur.code)
            raise erreur from exc
        except (ErreurRelancable, ErreurDefinitive, RessourceAbsente) as erreur:
            self._tracer(operation, methode, route, statut, debut, "ECHEC", erreur.code)
            raise
        self._tracer(operation, methode, route, statut, debut, "SUCCES", None)
        return corps

    def _interpreter(self, reponse: httpx.Response) -> dict[str, Any]:
        statut = reponse.status_code
        if 200 <= statut < 300:
            try:
                corps = reponse.json()
            except ValueError as exc:
                raise ErreurDefinitive("REPONSE_INATTENDUE", "réponse non JSON", status=statut) from exc
            if not isinstance(corps, dict) or corps.get("success") is not True:
                raise ErreurDefinitive("REPONSE_INATTENDUE", "champ success absent ou faux", status=statut)
            return corps
        message = _message_pipedrive(reponse)
        if statut == 404:
            raise RessourceAbsente("RESSOURCE_ABSENTE", message, status=statut)
        if statut == 429:
            raise ErreurRelancable("LIMITE_DEBIT", message, status=statut, retry_after=_retry_after(reponse))
        if statut >= 500:
            raise ErreurRelancable("ERREUR_SERVEUR", message, status=statut, retry_after=_retry_after(reponse))
        raise ErreurDefinitive(_CODES_DEFINITIFS.get(statut, f"HTTP_{statut}"), message, status=statut)

    def _tracer(self, operation: str, methode: str, route: str, statut: int | None, debut: float,
                resultat: str, code_erreur: str | None) -> None:
        appel = AppelPipedrive(
            operation=operation, methode=methode, route=route, statut=statut,
            duree_ms=int((time.perf_counter() - debut) * 1000), resultat=resultat,
            code_erreur=code_erreur, correlation_id=get_correlation_id(),
        )
        logger.log(
            logging.INFO if resultat == "SUCCES" else logging.WARNING,
            "%s %s %s -> %s", operation, methode, route, statut if statut is not None else code_erreur,
            extra={"operation": operation, "resultat": resultat, "code_erreur": code_erreur,
                   "duree_ms": appel.duree_ms},
        )
        if self.on_appel:
            self.on_appel(appel)
