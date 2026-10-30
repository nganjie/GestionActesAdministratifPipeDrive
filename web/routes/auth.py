"""UC01 : connexion et déconnexion."""

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from web.api import ApiErreur
from web.outils import api, stockage, utilisateur

bp = Blueprint("auth", __name__)


def _cible_sure(cible: str | None) -> str:
    """N'autorise qu'un chemin interne (évite les redirections ouvertes)."""
    if cible and cible.startswith("/") and not cible.startswith("//") and not urlparse(cible).netloc:
        return cible
    return url_for("tableau.accueil")


@bp.route("/connexion", methods=["GET", "POST"])
def connexion():  # noqa: ANN201
    if utilisateur() is not None:
        return redirect(url_for("tableau.accueil"))
    erreur = None
    identifiant = ""
    if request.method == "POST":
        identifiant = request.form.get("identifiant", "").strip()
        try:
            client = api()
            jetons = client.connecter(identifiant, request.form.get("mot_de_passe", ""))
            profil = client.get("/auth/me")
            if profil["role"] == "ADMIN":
                profil["mode_demo"] = client.get("/admin/demo")["actif"]
        except ApiErreur as exc:
            erreur = exc.message
        else:
            stockage().supprimer(session.get("sid"))
            session.clear()
            session["sid"] = stockage().creer({"jetons": jetons, "utilisateur": profil})
            flash(f"Bienvenue, {profil['nom']}.", "succes")
            return redirect(_cible_sure(request.args.get("suivant")))
    return render_template("connexion.html", erreur=erreur, identifiant=identifiant)


@bp.post("/deconnexion")
def deconnexion():  # noqa: ANN201
    if utilisateur() is not None:
        api().deconnecter()
    stockage().supprimer(session.get("sid"))
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("auth.connexion"))
