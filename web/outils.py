"""Outils partagés par les vues : client d'API de la requête, utilisateur connecté, contrôle des rôles."""

import functools
import uuid
from collections.abc import Callable
from typing import Any

from flask import current_app, flash, g, redirect, request, session, url_for

from web.api import ApiErreur, ClientApi


def stockage():  # noqa: ANN201
    return current_app.extensions["stockage_sessions"]


def api() -> ClientApi:
    """Client d'API lié à la session courante ; les jetons renouvelés sont réenregistrés côté serveur."""
    if "api" not in g:
        sid = session.get("sid")
        donnees = stockage().lire(sid) if sid else None
        jetons = donnees.get("jetons") if donnees else None

        def _memoriser(nouveaux: dict[str, str]) -> None:
            if sid and donnees is not None:
                stockage().enregistrer(sid, {**donnees, "jetons": nouveaux})

        g.correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        g.api = ClientApi(current_app.config["API_BASE_URL"], jetons, _memoriser, g.correlation_id,
                          transport=current_app.config.get("API_TRANSPORT"))
    return g.api


def utilisateur() -> dict[str, Any] | None:
    return g.get("utilisateur")


def connexion_requise(vue: Callable) -> Callable:
    @functools.wraps(vue)
    def _vue(*args: Any, **kwargs: Any):  # noqa: ANN202
        if utilisateur() is None:
            return redirect(url_for("auth.connexion", suivant=request.full_path.rstrip("?")))
        return vue(*args, **kwargs)
    return _vue


def roles_requis(*roles: str) -> Callable:
    def _decorateur(vue: Callable) -> Callable:
        @functools.wraps(vue)
        @connexion_requise
        def _vue(*args: Any, **kwargs: Any):  # noqa: ANN202
            if utilisateur()["role"] not in roles:
                flash("Vous n'avez pas les droits nécessaires pour cette page.", "erreur")
                return redirect(url_for("tableau.accueil"))
            return vue(*args, **kwargs)
        return _vue
    return _decorateur


def message_erreur(exc: ApiErreur) -> str:
    texte = exc.message
    if exc.code == "DOUBLON_DETECTE" and exc.extra.get("reference_existante"):
        texte += f" Dossier existant : {exc.extra['reference_existante']}."
    if exc.extra.get("statut_courant"):
        from web.libelles import libelle_statut

        texte += f" Statut actuel : {libelle_statut(exc.extra['statut_courant'])}."
    details_sans_champ = [d.get("erreur") for d in exc.details if d.get("champ") in (None, "", "pieces")]
    if details_sans_champ:
        texte += " " + " ; ".join(str(d) for d in details_sans_champ if d)
    return texte


def flasher_erreur(exc: ApiErreur) -> None:
    flash(message_erreur(exc), "erreur")


def formulaire() -> dict[str, str]:
    return {k: v for k, v in request.form.items() if k != "csrf"}
