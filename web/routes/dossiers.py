"""Dossiers : UC03 à UC12 (création, consultation, liste, modification, pièces, complétude, transitions,
décision, historique, annulation) et suivi Pipedrive (UC04, UC13, UC14)."""

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from web.api import ApiErreur
from web.formulaires import FORMULAIRES, PREFIXE, aplatir, demandeur, donnees_specifiques, lignes_resume
from web.libelles import ORDRE_CYCLE, STATUTS
from web.outils import api, connexion_requise, flasher_erreur, formulaire, message_erreur, roles_requis, utilisateur
from web.regles import actions_dossier, peut_creer, peut_declarer_pieces

bp = Blueprint("dossiers", __name__, url_prefix="/dossiers")

ONGLETS = ("resume", "pieces", "historique", "pipedrive")
FILTRES = ("statut", "type", "categorie", "reference", "demandeur", "cree_du", "cree_au")


def _demarches(actives: bool = True) -> list[dict]:
    return [d for d in api().get("/demarches") if d["actif"] or not actives]


def _vers_detail(dossier_id: str, onglet: str = "resume"):  # noqa: ANN202
    return redirect(url_for("dossiers.detail", dossier_id=dossier_id, onglet=onglet))


# --- UC05 Liste --------------------------------------------------------------------------------------------

@bp.get("/")
@connexion_requise
def liste():  # noqa: ANN201
    filtres = {k: request.args.get(k, "").strip() for k in FILTRES}
    page = max(1, request.args.get("page", 1, type=int))
    try:
        resultat = api().get("/dossiers", page=page, taille=20, **filtres)
    except ApiErreur as exc:
        if exc.status != 400:
            raise
        flash("Filtre invalide : " + "; ".join(f"{d['champ']} — {d['erreur']}" for d in exc.details), "erreur")
        resultat = {"elements": [], "total": 0, "page": 1, "taille": 20}
    pages = max(1, -(-resultat["total"] // resultat["taille"]))
    return render_template("dossiers/liste.html", resultat=resultat, filtres=filtres, page=page, pages=pages,
                           demarches=_demarches(actives=False), statuts=STATUTS,
                           peut_creer=peut_creer(utilisateur()["role"]))


# --- UC03 Création -----------------------------------------------------------------------------------------

def _corps_dossier(type_: str, valeurs: dict[str, str]) -> dict:
    return {
        "objet": valeurs.get("objet", "").strip(),
        "demandeur": demandeur(valeurs),
        "donnees_specifiques": donnees_specifiques(type_, valeurs),
    }


@bp.route("/nouveau", methods=["GET", "POST"])
@roles_requis("ACCUEIL")
def nouveau():  # noqa: ANN201
    demarches = _demarches()
    type_ = request.values.get("type") or (demarches[0]["code"] if demarches else "")
    demarche = next((d for d in demarches if d["code"] == type_), None)
    valeurs: dict[str, str] = formulaire() if request.method == "POST" else {}
    erreurs: dict[str, str] = {}
    doublon = None
    if request.method == "POST" and demarche:
        corps = {"type_demarche": type_, **_corps_dossier(type_, valeurs)}
        if valeurs.get("confirmer_doublon"):
            corps["confirmer_doublon"] = True
            corps["motif_doublon"] = valeurs.get("motif_doublon", "").strip() or None
        try:
            dossier = api().post("/dossiers", corps)
        except ApiErreur as exc:
            if exc.code == "DOUBLON_DETECTE":
                doublon = exc.extra
            elif exc.status == 400:
                erreurs = exc.erreurs_champs
                flash("Le formulaire contient des erreurs : corrigez les champs signalés.", "erreur")
            else:
                if exc.code == "MOTIF_OBLIGATOIRE":
                    erreurs["motif_doublon"] = exc.message
                    doublon = {"reference_existante": valeurs.get("reference_doublon"),
                               "dossier_id": valeurs.get("dossier_doublon")}
                flasher_erreur(exc)
        else:
            flash(f"Dossier {dossier['reference']} créé en brouillon. Déclarez les pièces puis soumettez-le.",
                  "succes")
            return _vers_detail(dossier["id"], "pieces")
    return render_template("dossiers/formulaire.html", mode="creation", demarches=demarches, demarche=demarche,
                           type_=type_, formulaire=FORMULAIRES.get(type_), valeurs=valeurs, erreurs=erreurs,
                           doublon=doublon, prefixe=PREFIXE)


# --- UC04 / UC11 Consultation --------------------------------------------------------------------------------

def _frise(dossier: dict) -> list[dict]:
    statut = dossier["statut"]
    rang = {"INCOMPLET": 1, "APPROUVE": 4, "REJETE": 4, "ANNULE": -1}
    position = ORDRE_CYCLE.index(statut) if statut in ORDRE_CYCLE else rang.get(statut, 0)
    if statut == "DELIVRE":
        position = len(ORDRE_CYCLE)
    etapes = []
    for i, code in enumerate(ORDRE_CYCLE):
        libelle = STATUTS.get(code, ("Décision", ""))[0]
        if code == "DECISION" and dossier.get("decision"):
            libelle = STATUTS[dossier["decision"]["issue"]][0]
        etat = "fait" if i < position else ("courant" if i == position else "a_venir")
        if statut in ("INCOMPLET",) and code == "SOUMIS":
            libelle, etat = "Incomplet", "bloque"
        etapes.append({"libelle": libelle, "etat": etat, "numero": i + 1})
    return etapes


def _pieces(dossier: dict) -> list[dict]:
    lignes = []
    for requise in dossier["pieces_requises"]:
        fournies = [p for p in dossier["pieces_fournies"] if p["code_piece"] == requise["code"]]
        active = next((p for p in reversed(fournies) if p["etat"] != "RETIREE"), None)
        lignes.append({**requise, "fournie": active, "retirees": [p for p in fournies if p["etat"] == "RETIREE"]})
    return lignes


@bp.get("/<uuid:dossier_id>")
@connexion_requise
def detail(dossier_id):  # noqa: ANN001, ANN201
    onglet = request.args.get("onglet", "resume")
    onglet = onglet if onglet in ONGLETS else "resume"
    client = api()
    dossier = client.get(f"/dossiers/{dossier_id}")
    historique = client.get(f"/dossiers/{dossier_id}/historique")
    role = utilisateur()["role"]
    pieces = _pieces(dossier)
    return render_template(
        "dossiers/detail.html", dossier=dossier, onglet=onglet, historique=historique, pieces=pieces,
        manquantes=[p for p in pieces if p["obligatoire"] and (p["fournie"] or {}).get("etat") != "CONFORME"],
        actions=actions_dossier(role, dossier["statut"]), frise=_frise(dossier),
        resume=lignes_resume(dossier["type_demarche"], dossier["donnees_specifiques"]),
        peut_pieces=peut_declarer_pieces(role, dossier["statut"]),
    )


@bp.get("/<uuid:dossier_id>/activites")
@connexion_requise
def activites(dossier_id):  # noqa: ANN001, ANN201
    resultat = api().get(f"/dossiers/{dossier_id}/activites")
    gabarit = "partials/activites.html" if request.headers.get("HX-Request") else "dossiers/activites_page.html"
    return render_template(gabarit, activites=resultat, dossier_id=dossier_id)


# --- UC06 Modification -------------------------------------------------------------------------------------

@bp.route("/<uuid:dossier_id>/modifier", methods=["GET", "POST"])
@roles_requis("ACCUEIL")
def modifier(dossier_id):  # noqa: ANN001, ANN201
    client = api()
    dossier = client.get(f"/dossiers/{dossier_id}")
    type_ = dossier["type_demarche"]
    erreurs: dict[str, str] = {}
    if request.method == "POST":
        valeurs = formulaire()
        try:
            client.patch(f"/dossiers/{dossier_id}", _corps_dossier(type_, valeurs))
        except ApiErreur as exc:
            if exc.status == 400:
                erreurs = exc.erreurs_champs
                flash("Le formulaire contient des erreurs : corrigez les champs signalés.", "erreur")
            else:
                flasher_erreur(exc)
        else:
            flash("Brouillon mis à jour.", "succes")
            return _vers_detail(dossier_id)
    else:
        d = dossier["demandeur"]
        valeurs = {"objet": dossier["objet"], **aplatir(dossier["donnees_specifiques"]),
                   **{f"demandeur.{k}": str(d[k]) for k in ("nom", "prenom", "telephone", "email", "date_naissance")
                      if d.get(k)}}
    demarche = {"code": type_, "libelle": dossier["libelle_demarche"], "categorie": dossier["categorie"]}
    return render_template("dossiers/formulaire.html", mode="modification", dossier=dossier, demarches=[demarche],
                           demarche=demarche, type_=type_, formulaire=FORMULAIRES.get(type_), valeurs=valeurs,
                           erreurs=erreurs, doublon=None, prefixe=PREFIXE)


# --- UC07 Pièces ---------------------------------------------------------------------------------------------

@bp.post("/<uuid:dossier_id>/pieces")
@connexion_requise
def declarer_piece(dossier_id):  # noqa: ANN001, ANN201
    f = formulaire()
    corps = {"code_piece": f.get("code_piece", ""),
             "date_reception": f.get("date_reception") or date.today().isoformat(),
             "etat": f.get("etat", "CONFORME"), "observation": f.get("observation", "").strip() or None}
    try:
        api().post(f"/dossiers/{dossier_id}/pieces", corps)
        flash("Pièce déclarée.", "succes")
    except ApiErreur as exc:
        flash(message_erreur(exc) + _details(exc), "erreur")
    return _vers_detail(dossier_id, "pieces")


@bp.post("/<uuid:dossier_id>/pieces/<uuid:piece_id>")
@connexion_requise
def maj_piece(dossier_id, piece_id):  # noqa: ANN001, ANN201
    f = formulaire()
    corps = {k: v for k, v in {"etat": f.get("etat"), "observation": f.get("observation", "").strip() or None,
                               "date_reception": f.get("date_reception") or None}.items() if v is not None}
    try:
        api().patch(f"/dossiers/{dossier_id}/pieces/{piece_id}", corps)
        flash("Pièce mise à jour.", "succes")
    except ApiErreur as exc:
        flash(message_erreur(exc) + _details(exc), "erreur")
    return _vers_detail(dossier_id, "pieces")


def _details(exc: ApiErreur) -> str:
    champs = [f"{d['champ']} : {d['erreur']}" for d in exc.details if d.get("champ") not in (None, "", "pieces")]
    return (" — " + " ; ".join(champs)) if champs else ""


# --- UC08 Complétude ----------------------------------------------------------------------------------------

@bp.post("/<uuid:dossier_id>/verification")
@connexion_requise
def verification(dossier_id):  # noqa: ANN001, ANN201
    try:
        r = api().post(f"/dossiers/{dossier_id}/verification-completude")
    except ApiErreur as exc:
        flasher_erreur(exc)
        return _vers_detail(dossier_id, "pieces")
    if r["complet"]:
        flash("Dossier complet : toutes les pièces requises sont conformes. Vous pouvez passer en instruction.",
              "succes")
    else:
        manquantes = ", ".join(p["libelle"] for p in r["pieces_manquantes"])
        suite = ""
        if r["statut"] == "INCOMPLET":
            suite = " Le dossier est passé « Incomplet » et une relance est programmée."
        flash(f"Pièces manquantes ou à corriger : {manquantes}.{suite}", "attention")
    return _vers_detail(dossier_id, "pieces")


# --- UC09 Transitions --------------------------------------------------------------------------------------

@bp.post("/<uuid:dossier_id>/transition")
@connexion_requise
def transition(dossier_id):  # noqa: ANN001, ANN201
    f = formulaire()
    corps = {"statut_cible": f.get("cible", ""), "motif": f.get("motif", "").strip() or None,
             "commentaire": f.get("commentaire", "").strip() or None}
    try:
        dossier = api().post(f"/dossiers/{dossier_id}/transitions", corps)
        flash(f"Dossier passé au statut « {STATUTS[dossier['statut']][0]} ».", "succes")
    except ApiErreur as exc:
        flash(message_erreur(exc) + _details(exc), "erreur")
    return _vers_detail(dossier_id)


# --- UC10 Décision -------------------------------------------------------------------------------------------

@bp.route("/<uuid:dossier_id>/decision", methods=["GET", "POST"])
@roles_requis("RESPONSABLE")
def decision(dossier_id):  # noqa: ANN001, ANN201
    client = api()
    dossier = client.get(f"/dossiers/{dossier_id}")
    erreurs: dict[str, str] = {}
    valeurs = formulaire() if request.method == "POST" else {"issue": "APPROUVE"}
    if request.method == "POST":
        corps = {"issue": valeurs.get("issue"), "motif": valeurs.get("motif", "").strip() or None}
        try:
            dossier = client.post(f"/dossiers/{dossier_id}/decision", corps)
        except ApiErreur as exc:
            if exc.code == "MOTIF_OBLIGATOIRE" or "motif" in exc.erreurs_champs:
                erreurs["motif"] = exc.erreurs_champs.get("motif") or exc.message
            else:
                flasher_erreur(exc)
        else:
            flash(f"Décision enregistrée : {STATUTS[dossier['statut']][0]}.", "succes")
            return _vers_detail(dossier_id)
    return render_template("dossiers/decision.html", dossier=dossier, valeurs=valeurs, erreurs=erreurs,
                           pieces=_pieces(dossier))


# --- UC12 Annulation -----------------------------------------------------------------------------------------

@bp.route("/<uuid:dossier_id>/annulation", methods=["GET", "POST"])
@roles_requis("ACCUEIL", "RESPONSABLE")
def annulation(dossier_id):  # noqa: ANN001, ANN201
    client = api()
    dossier = client.get(f"/dossiers/{dossier_id}")
    erreurs: dict[str, str] = {}
    motif = ""
    if request.method == "POST":
        motif = request.form.get("motif", "").strip()
        try:
            client.post(f"/dossiers/{dossier_id}/annulation", {"motif": motif or None})
        except ApiErreur as exc:
            if exc.code == "MOTIF_OBLIGATOIRE" or "motif" in exc.erreurs_champs:
                erreurs["motif"] = exc.erreurs_champs.get("motif") or exc.message
            else:
                flasher_erreur(exc)
        else:
            flash("Dossier annulé.", "succes")
            return _vers_detail(dossier_id)
    return render_template("dossiers/annulation.html", dossier=dossier, erreurs=erreurs, motif=motif)
