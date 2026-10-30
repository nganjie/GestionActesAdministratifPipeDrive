"""Client de l'API intermédiaire : l'application web n'accède ni à la base ni à Pipedrive (CDC §3.1)."""

import contextlib
from collections.abc import Callable
from typing import Any

import httpx


class ApiErreur(Exception):
    """Erreur renvoyée par l'API, au format {code, message, details, correlation_id} (FRS §7.2)."""

    def __init__(self, status: int, code: str, message: str, details: list[dict] | None = None,
                 extra: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        self.extra = extra or {}
        super().__init__(f"{status} {code}: {message}")

    @property
    def erreurs_champs(self) -> dict[str, str]:
        return {d.get("champ", ""): d.get("erreur", "") for d in self.details if d.get("champ")}


class SessionExpiree(Exception):
    """Le jeton d'accès et le jeton de rafraîchissement ne sont plus valides : reconnexion nécessaire."""


class ClientApi:
    def __init__(self, base_url: str, jetons: dict[str, str] | None = None,
                 sur_renouvellement: Callable[[dict[str, str]], None] | None = None,
                 correlation_id: str | None = None, timeout: float = 15.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.jetons = jetons
        self.sur_renouvellement = sur_renouvellement
        self.correlation_id = correlation_id
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def fermer(self) -> None:
        self._http.close()

    # --- Bas niveau ---------------------------------------------------------------------------------

    def _envoyer(self, methode: str, chemin: str, *, json: Any = None, params: dict | None = None,
                 authentifie: bool = True) -> httpx.Response:
        entetes = {"Accept": "application/json"}
        if self.correlation_id:
            entetes["X-Correlation-Id"] = self.correlation_id
        if authentifie and self.jetons:
            entetes["Authorization"] = f"Bearer {self.jetons['access_token']}"
        propres = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            return self._http.request(methode, chemin, json=json, params=propres, headers=entetes)
        except httpx.TimeoutException as exc:
            raise ApiErreur(504, "API_DELAI_DEPASSE", "L'API n'a pas répondu à temps.") from exc
        except httpx.TransportError as exc:
            raise ApiErreur(503, "API_INDISPONIBLE", "L'API est injoignable. Vérifiez qu'elle est démarrée.") from exc

    @staticmethod
    def _erreur(reponse: httpx.Response) -> ApiErreur:
        try:
            corps = reponse.json()
        except ValueError:
            corps = {}
        if not isinstance(corps, dict):
            corps = {}
        extra = {k: v for k, v in corps.items() if k not in ("code", "message", "details", "correlation_id")}
        return ApiErreur(reponse.status_code, corps.get("code", f"HTTP_{reponse.status_code}"),
                         corps.get("message", "Erreur inattendue de l'API."), corps.get("details"), extra)

    def _renouveler(self) -> bool:
        if not self.jetons or not self.jetons.get("refresh_token"):
            return False
        r = self._envoyer("POST", "/auth/refresh", json={"refresh_token": self.jetons["refresh_token"]},
                          authentifie=False)
        if r.status_code != 200:
            return False
        donnees = r.json()
        self.jetons = {"access_token": donnees["access_token"], "refresh_token": donnees["refresh_token"]}
        if self.sur_renouvellement:
            self.sur_renouvellement(self.jetons)
        return True

    def requete(self, methode: str, chemin: str, *, json: Any = None, params: dict | None = None,
                authentifie: bool = True) -> Any:
        r = self._envoyer(methode, chemin, json=json, params=params, authentifie=authentifie)
        if r.status_code == 401 and authentifie:
            if not self._renouveler():
                raise SessionExpiree()
            r = self._envoyer(methode, chemin, json=json, params=params, authentifie=True)
            if r.status_code == 401:
                raise SessionExpiree()
        if r.status_code >= 400:
            raise self._erreur(r)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def get(self, chemin: str, **params: Any) -> Any:
        return self.requete("GET", chemin, params=params)

    def post(self, chemin: str, json: Any = None) -> Any:
        return self.requete("POST", chemin, json=json if json is not None else {})

    def patch(self, chemin: str, json: Any) -> Any:
        return self.requete("PATCH", chemin, json=json)

    # --- Authentification (UC01) ----------------------------------------------------------------------

    def connecter(self, identifiant: str, mot_de_passe: str) -> dict[str, str]:
        donnees = self.requete("POST", "/auth/login", json={"identifiant": identifiant, "mot_de_passe": mot_de_passe},
                               authentifie=False)
        self.jetons = {"access_token": donnees["access_token"], "refresh_token": donnees["refresh_token"]}
        return self.jetons

    def deconnecter(self) -> None:
        if not self.jetons:
            return
        with contextlib.suppress(ApiErreur, SessionExpiree):
            self.requete("POST", "/auth/logout", json={"refresh_token": self.jetons["refresh_token"]})
