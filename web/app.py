"""Application web des agents (Flask + Jinja + htmx), cliente de l'API intermédiaire.

Lancement : `uv run flask --app web.app run --port 5000`
"""

import logging
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from web.api import ApiErreur, SessionExpiree
from web.config import ConfigWeb
from web.libelles import (
    CATEGORIES,
    ETATS_PIECE,
    OBJETS_SYNCHRO,
    ROLES,
    SYNCHRO,
    TYPES_EVENEMENT,
    classe_statut,
    libelle_statut,
)
from web.outils import api, stockage
from web.sessions import StockageSessions

logger = logging.getLogger("web")
METHODES_SURES = {"GET", "HEAD", "OPTIONS"}


def _date(valeur: Any, format_: str = "%d/%m/%Y") -> str:
    if not valeur:
        return "—"
    if isinstance(valeur, str):
        try:
            valeur = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
        except ValueError:
            try:
                valeur = date.fromisoformat(valeur)
            except ValueError:
                return valeur
    if isinstance(valeur, datetime):
        valeur = valeur.astimezone()
    return valeur.strftime(format_)


def create_app(surcharges: dict[str, Any] | None = None) -> Flask:
    config = ConfigWeb()
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        API_BASE_URL=config.web_api_url,
        SECRET_KEY=config.web_secret_key or secrets.token_urlsafe(48),
        SESSIONS_DIR=config.web_sessions_dir,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.web_cookie_secure,
        API_TRANSPORT=None,
    )
    if not config.web_secret_key:
        logger.warning("WEB_SECRET_KEY non défini : clé temporaire, les sessions seront perdues au redémarrage")
    app.config.update(surcharges or {})
    dossier_sessions = Path(app.config["SESSIONS_DIR"])
    if not dossier_sessions.is_absolute():
        dossier_sessions = Path(app.root_path).parent / dossier_sessions
    app.extensions["stockage_sessions"] = StockageSessions(dossier_sessions)

    # --- Session, utilisateur et CSRF -----------------------------------------------------------------

    @app.before_request
    def _avant() -> Any:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        if request.method not in METHODES_SURES:
            jeton = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
            if not jeton or not secrets.compare_digest(jeton, session["csrf"]):
                abort(400, "Jeton de sécurité invalide : rechargez la page et recommencez.")
        g.utilisateur = None
        sid = session.get("sid")
        if sid:
            donnees = stockage().lire(sid)
            if donnees is None:
                session.pop("sid", None)
            else:
                g.utilisateur = donnees.get("utilisateur")
        return None

    @app.teardown_request
    def _fermer(_: BaseException | None) -> None:
        client = g.pop("api", None)
        if client is not None:
            client.fermer()

    @app.after_request
    def _entetes(reponse):  # noqa: ANN001, ANN202
        reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
        reponse.headers.setdefault("X-Frame-Options", "DENY")
        reponse.headers.setdefault("Referrer-Policy", "same-origin")
        return reponse

    # --- Erreurs -------------------------------------------------------------------------------------

    @app.errorhandler(SessionExpiree)
    def _session_expiree(_: SessionExpiree):  # noqa: ANN202
        stockage().supprimer(session.pop("sid", None))
        flash("Votre session a expiré. Reconnectez-vous.", "info")
        cible = url_for("auth.connexion")
        if request.headers.get("HX-Request"):
            return "", 204, {"HX-Redirect": cible}
        return redirect(cible)

    @app.errorhandler(ApiErreur)
    def _api_erreur(exc: ApiErreur):  # noqa: ANN202
        if exc.status == 404:
            message = "Cette ressource n'existe pas ou ne fait pas partie de votre périmètre."
            return render_template("erreur.html", titre="Introuvable", message=message), 404
        if exc.status == 403:
            return render_template("erreur.html", titre="Accès refusé", message=exc.message), 403
        return render_template("erreur.html", titre="Service indisponible", message=exc.message,
                               code=exc.code), 502

    @app.errorhandler(400)
    def _requete_invalide(exc):  # noqa: ANN001, ANN202
        return render_template("erreur.html", titre="Requête invalide", message=exc.description), 400

    @app.errorhandler(404)
    def _introuvable(_):  # noqa: ANN001, ANN202
        return render_template("erreur.html", titre="Page introuvable",
                               message="Cette page n'existe pas."), 404

    # --- Gabarits ------------------------------------------------------------------------------------

    app.jinja_env.filters.update(
        date=_date,
        dateheure=lambda v: _date(v, "%d/%m/%Y %H:%M"),
        statut=libelle_statut,
        classe_statut=classe_statut,
        role=lambda r: ROLES.get(r, r or "—"),
        categorie=lambda c: CATEGORIES.get(c, c or "—"),
        etat_piece=lambda e: ETATS_PIECE.get(e, e),
        evenement=lambda t: TYPES_EVENEMENT.get(t, t),
        objet_synchro=lambda o: OBJETS_SYNCHRO.get(o, o),
    )

    @app.context_processor
    def _contexte() -> dict[str, Any]:
        return {
            "utilisateur": g.get("utilisateur"),
            "csrf_token": session.get("csrf", ""),
            "SYNCHRO": SYNCHRO,
            "ROLES": ROLES,
            "CATEGORIES": CATEGORIES,
            "aujourdhui": date.today().isoformat(),
        }

    from web.routes import admin, auth, dossiers, tableau

    for module in (auth, tableau, dossiers, admin):
        app.register_blueprint(module.bp)

    @app.get("/sante")
    def _sante():  # noqa: ANN202
        try:
            api().requete("GET", "/sante", authentifie=False)
            return {"web": "ok", "api": "ok"}
        except ApiErreur as exc:
            return {"web": "ok", "api": exc.code}, 503

    return app


app = create_app()
