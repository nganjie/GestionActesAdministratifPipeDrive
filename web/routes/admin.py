"""Administration : comptes (UC02), démarches (UC16), synchronisations (UC15), journaux et santé (UC17)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from web.api import ApiErreur
from web.libelles import CATEGORIES, ROLES
from web.outils import api, flasher_erreur, formulaire, roles_requis

bp = Blueprint("admin", __name__, url_prefix="/admin")


# --- UC02 Comptes ------------------------------------------------------------------------------------------

@bp.route("/utilisateurs", methods=["GET", "POST"])
@roles_requis("ADMIN")
def utilisateurs():  # noqa: ANN201
    client = api()
    erreurs: dict[str, str] = {}
    valeurs: dict[str, str] = {}
    if request.method == "POST":
        valeurs = formulaire()
        corps = {"nom": valeurs.get("nom", "").strip(), "identifiant": valeurs.get("identifiant", "").strip(),
                 "mot_de_passe": valeurs.get("mot_de_passe", ""), "role": valeurs.get("role"),
                 "categorie": valeurs.get("categorie") or None}
        try:
            u = client.post("/utilisateurs", corps)
        except ApiErreur as exc:
            erreurs = exc.erreurs_champs
            if exc.status == 409:
                erreurs["identifiant"] = exc.message
            if not erreurs:
                flasher_erreur(exc)
        else:
            flash(f"Compte « {u['identifiant']} » créé.", "succes")
            return redirect(url_for("admin.utilisateurs"))
    return render_template("admin/utilisateurs.html", comptes=client.get("/utilisateurs"), erreurs=erreurs,
                           valeurs=valeurs, roles=ROLES, categories=CATEGORIES)


@bp.post("/utilisateurs/<uuid:utilisateur_id>")
@roles_requis("ADMIN")
def modifier_utilisateur(utilisateur_id):  # noqa: ANN001, ANN201
    f = formulaire()
    corps: dict = {}
    if "role" in f:
        corps["role"] = f["role"]
    if "actif" in f:
        corps["actif"] = f["actif"] == "true"
    if f.get("mot_de_passe"):
        corps["mot_de_passe"] = f["mot_de_passe"]
    try:
        u = api().patch(f"/utilisateurs/{utilisateur_id}", corps)
        flash(f"Compte « {u['identifiant']} » mis à jour.", "succes")
    except ApiErreur as exc:
        details = "; ".join(f"{d.get('champ')} : {d.get('erreur')}" for d in exc.details)
        flash(exc.message + (f" ({details})" if details else ""), "erreur")
    return redirect(url_for("admin.utilisateurs"))


# --- UC16 Démarches et pièces requises ------------------------------------------------------------------

@bp.get("/demarches")
@roles_requis("ADMIN")
def demarches():  # noqa: ANN201
    return render_template("admin/demarches.html", demarches=api().get("/demarches"))


@bp.post("/demarches/<code>")
@roles_requis("ADMIN")
def modifier_demarche(code: str):  # noqa: ANN201
    f = formulaire()
    corps: dict = {}
    if f.get("libelle"):
        corps["libelle"] = f["libelle"].strip()
    if "actif" in f:
        corps["actif"] = f["actif"] == "true"
    try:
        api().patch(f"/admin/demarches/{code}", corps)
        flash("Démarche mise à jour.", "succes")
    except ApiErreur as exc:
        flasher_erreur(exc)
    return redirect(url_for("admin.demarches") + f"#{code}")


@bp.post("/demarches/<code>/pieces")
@roles_requis("ADMIN")
def ajouter_piece(code: str):  # noqa: ANN201
    f = formulaire()
    corps = {"code": f.get("code", "").strip().upper(), "libelle": f.get("libelle", "").strip(),
             "obligatoire": f.get("obligatoire") == "true"}
    try:
        api().post(f"/admin/demarches/{code}/pieces", corps)
        flash("Pièce requise ajoutée. Elle s'applique aux nouveaux dossiers.", "succes")
    except ApiErreur as exc:
        details = "; ".join(f"{d.get('champ')} : {d.get('erreur')}" for d in exc.details)
        flash(exc.message + (f" ({details})" if details else ""), "erreur")
    return redirect(url_for("admin.demarches") + f"#{code}")


@bp.post("/demarches/<code>/pieces/<uuid:piece_id>")
@roles_requis("ADMIN")
def modifier_piece(code: str, piece_id):  # noqa: ANN001, ANN201
    f = formulaire()
    corps: dict = {}
    if f.get("libelle"):
        corps["libelle"] = f["libelle"].strip()
    for cle in ("obligatoire", "actif"):
        if cle in f:
            corps[cle] = f[cle] == "true"
    try:
        api().patch(f"/admin/demarches/{code}/pieces/{piece_id}", corps)
        flash("Pièce requise mise à jour.", "succes")
    except ApiErreur as exc:
        flasher_erreur(exc)
    return redirect(url_for("admin.demarches") + f"#{code}")


# --- UC15 Synchronisations et UC17 santé ------------------------------------------------------------------

@bp.get("/synchronisations")
@roles_requis("ADMIN")
def synchronisations():  # noqa: ANN201
    client = api()
    etat = request.args.get("etat", "")
    page = max(1, request.args.get("page", 1, type=int))
    resultat = client.get("/synchronisations", etat=etat, page=page, taille=25)
    try:
        sante = client.get("/admin/sante/pipedrive")
    except ApiErreur:
        sante = None
    pages = max(1, -(-resultat["total"] // resultat["taille"]))
    return render_template("admin/synchronisations.html", resultat=resultat, etat=etat, page=page, pages=pages,
                           sante=sante)


@bp.post("/synchronisations/<uuid:reference_id>/relance")
@roles_requis("ADMIN")
def relancer(reference_id):  # noqa: ANN001, ANN201
    try:
        api().post(f"/synchronisations/{reference_id}/relance")
        flash("Relance programmée : le worker la traitera dans quelques secondes.", "succes")
    except ApiErreur as exc:
        flasher_erreur(exc)
    return redirect(request.referrer or url_for("admin.synchronisations"))


@bp.post("/synchronisations/relance-globale")
@roles_requis("ADMIN")
def relancer_tout():  # noqa: ANN201
    try:
        n = api().post("/synchronisations/relance-globale")["relancees"]
        flash(f"{n} synchronisation(s) en échec relancée(s).", "succes")
    except ApiErreur as exc:
        flasher_erreur(exc)
    return redirect(url_for("admin.synchronisations"))


@bp.get("/journaux")
@roles_requis("ADMIN")
def journaux():  # noqa: ANN201
    filtres = {k: request.args.get(k, "").strip() for k in ("niveau", "operation", "correlation_id")}
    page = max(1, request.args.get("page", 1, type=int))
    resultat = api().get("/admin/journaux", page=page, taille=50, **filtres)
    pages = max(1, -(-resultat["total"] // resultat["taille"]))
    return render_template("admin/journaux.html", resultat=resultat, filtres=filtres, page=page, pages=pages)
