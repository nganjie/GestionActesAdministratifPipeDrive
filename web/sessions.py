"""Stockage des sessions côté serveur : les jetons JWT ne quittent jamais le serveur web.

Le navigateur ne reçoit qu'un identifiant de session aléatoire dans un cookie signé.
"""

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

_ID_VALIDE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class StockageSessions:
    def __init__(self, dossier: str | Path, duree_vie: int = 8 * 3600):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.duree_vie = duree_vie

    def _chemin(self, sid: str) -> Path | None:
        if not sid or len(sid) > 64 or not set(sid) <= _ID_VALIDE:
            return None
        return self.dossier / f"{sid}.json"

    def creer(self, donnees: dict[str, Any]) -> str:
        sid = secrets.token_urlsafe(32)
        self.enregistrer(sid, donnees)
        return sid

    def enregistrer(self, sid: str, donnees: dict[str, Any]) -> None:
        chemin = self._chemin(sid)
        if chemin is None:
            return
        descripteur, temporaire = tempfile.mkstemp(dir=self.dossier, suffix=".tmp")
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            json.dump({**donnees, "_maj": time.time()}, f)
        os.replace(temporaire, chemin)

    def lire(self, sid: str | None) -> dict[str, Any] | None:
        chemin = self._chemin(sid or "")
        if chemin is None or not chemin.exists():
            return None
        try:
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - donnees.get("_maj", 0) > self.duree_vie:
            self.supprimer(sid)
            return None
        return donnees

    def supprimer(self, sid: str | None) -> None:
        chemin = self._chemin(sid or "")
        if chemin is not None:
            chemin.unlink(missing_ok=True)

    def purger(self) -> None:
        limite = time.time() - self.duree_vie
        for fichier in self.dossier.glob("*.json"):
            try:
                if fichier.stat().st_mtime < limite:
                    fichier.unlink(missing_ok=True)
            except OSError:
                continue
