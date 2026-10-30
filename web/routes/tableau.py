"""Tableau de bord : file de travail selon le rôle, répartition par statut, état de Pipedrive."""

from flask import Blueprint, render_template

from web.api import ApiErreur
from web.libelles import STATUTS
from web.outils import api, connexion_requise, utilisateur
from web.regles import est_admin, file_de_travail

bp = Blueprint("tableau", __name__)


@bp.get("/")
@connexion_requise
def accueil():  # noqa: ANN201
    client = api()
    role = utilisateur()["role"]
    repartition = []
    for code, (libelle, classe) in STATUTS.items():
        total = client.get("/dossiers", statut=code, taille=1)["total"]
        repartition.append({"code": code, "libelle": libelle, "classe": classe, "n": total})
    total = sum(r["n"] for r in repartition)

    file = []
    for statut in file_de_travail(role):
        file += client.get("/dossiers", statut=statut, taille=20)["elements"]
    file.sort(key=lambda d: d["maj_le"])

    recents = client.get("/dossiers", taille=6)["elements"]

    sante, synchros_echec = None, []
    if est_admin(role):
        try:
            sante = client.get("/admin/sante/pipedrive")
        except ApiErreur:
            sante = None
        synchros_echec = client.get("/synchronisations", etat="ECHEC", taille=5)["elements"]

    return render_template("tableau.html", repartition=repartition, total=total, file=file, recents=recents,
                           sante=sante, synchros_echec=synchros_echec)
