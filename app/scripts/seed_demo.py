"""Données de démonstration : comptes prêts à l'emploi et dossiers dans tous les statuts.

Lancement : `uv run python -m app.scripts.seed_demo`

Les dossiers sont créés par les services métier (comme si les agents avaient travaillé dans l'application) :
historique, règles et événements de synchronisation Pipedrive sont donc cohérents. Le script est idempotent :
les comptes existants sont conservés et les dossiers ne sont ajoutés que si la base n'en contient aucun.
Toutes les données sont fictives.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.base import dispose_engine, init_engine
from app.db.models import Dossier, Utilisateur
from app.domain.enums import Categorie, EtatPiece, IssueDecision, Role, Statut
from app.schemas.api import DossierCreation, PieceDeclaration, UtilisateurCreation
from app.services import auth, demarches, dossiers
from app.services.contexte import UtilisateurCourant


@dataclass(frozen=True)
class Compte:
    identifiant: str
    mot_de_passe: str
    nom: str
    role: Role


# Mêmes comptes que docs/SCENARIO_DE_TEST.md (données fictives, à ne jamais utiliser en production).
COMPTES = (
    Compte("accueil", "MotDePasse-Accueil1", "Léa Abena", Role.ACCUEIL),
    Compte("civil", "MotDePasse-Civil1", "Awa Ndzana", Role.AGENT_ETAT_CIVIL),
    Compte("certif", "MotDePasse-Certif1", "Eric Kamga", Role.AGENT_CERTIFICATION),
    Compte("chef", "MotDePasse-Chef1", "Paul Manga", Role.RESPONSABLE),
    Compte("chef2", "MotDePasse-Chef2", "Rose Essomba", Role.RESPONSABLE),
)


def _jours(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _demandeur(nom: str, prenom: str, telephone: str, email: str | None = None) -> dict[str, Any]:
    d = {"nom": nom, "prenom": prenom, "telephone": telephone}
    if email:
        d["email"] = email
    return d


# (démarche, objet, demandeur, données spécifiques, pièces déclarées conformes, statut visé, instructeur)
# pieces = None : toutes les pièces requises ; liste : seulement ces codes.
DOSSIERS: list[dict[str, Any]] = [
    {"type": "DECES", "objet": "Établissement de l'acte de décès", "cible": Statut.DELIVRE, "instructeur": "civil",
     "demandeur": _demandeur("Mballa", "Jean", "690000001", "jean.mballa@example.cm"),
     "donnees": {"defunt": {"nom": "Mballa", "prenom": "Etienne", "date_naissance": "1948-03-12"},
                 "date_deces": _jours(-12), "lieu_deces": "Yaoundé", "lien_declarant": "Fils"}},
    {"type": "DECES", "objet": "Établissement de l'acte de décès", "cible": Statut.EN_INSTRUCTION,
     "instructeur": "civil", "demandeur": _demandeur("Ngono", "Marie", "677000002"),
     "donnees": {"defunt": {"nom": "Ngono", "prenom": "Albert"}, "date_deces": _jours(-4),
                 "lieu_deces": "Douala", "lien_declarant": "Épouse"}},
    {"type": "DECES", "objet": "Établissement de l'acte de décès", "cible": Statut.BROUILLON,
     "demandeur": _demandeur("Tchoupo", "Bernard", "699000003"), "pieces": [],
     "donnees": {"defunt": {"nom": "Tchoupo", "prenom": "Jeanne"}, "date_deces": _jours(-2),
                 "lieu_deces": "Bafoussam", "lien_declarant": "Neveu"}},
    {"type": "MARIAGE", "objet": "Célébration et établissement de l'acte de mariage", "cible": Statut.INCOMPLET,
     "instructeur": "civil", "pieces": ["IDENTITE_EPOUX", "JUSTIFICATIFS_RESIDENCE"],
     "demandeur": _demandeur("Ngo Biyong", "Clarisse", "655000004", "clarisse.ngobiyong@example.cm"),
     "donnees": {"epoux_1": {"nom": "Ngo Biyong", "prenom": "Clarisse", "date_naissance": "1995-06-02"},
                 "epoux_2": {"nom": "Essomba", "prenom": "Paul", "date_naissance": "1992-11-20"},
                 "date_celebration_prevue": _jours(45),
                 "temoins": [{"nom": "Abena", "prenom": "Luc"}, {"nom": "Manga", "prenom": "Sylvie"}]}},
    {"type": "COPIE_ACTE", "objet": "Copie intégrale d'acte de mariage", "cible": Statut.SOUMIS,
     "demandeur": _demandeur("Fouda", "Paul", "670000005"),
     "donnees": {"type_acte": "MARIAGE", "numero_acte": "456/2015", "annee": 2015,
                 "centre_etat_civil": "Centre principal de Yaoundé Ier", "nombre_copies": 2,
                 "qualite_demandeur": "Conjoint"}},
    {"type": "LEGALISATION", "objet": "Légalisation d'une attestation d'hébergement",
     "cible": Statut.EN_ATTENTE_DECISION, "instructeur": "certif",
     "demandeur": _demandeur("Atangana", "Marie", "691000006", "marie.atangana@example.cm"),
     "donnees": {"intitule_document": "Attestation d'hébergement", "signataire": {"nom": "Atangana", "prenom": "Marie"},
                 "qualite_signataire": "Propriétaire", "nombre_exemplaires": 2}},
    {"type": "CERTIFICATION_CONFORME", "objet": "Certification conforme de diplôme", "cible": Statut.APPROUVE,
     "instructeur": "certif", "demandeur": _demandeur("Ekani", "Samuel", "652000007"),
     "donnees": {"intitule_document": "Diplôme de licence en droit", "nombre_copies": 3}},
    {"type": "LEGALISATION", "objet": "Légalisation d'une procuration", "cible": Statut.REJETE,
     "instructeur": "certif", "motif": "Le signataire ne s'est pas présenté en personne au guichet.",
     "demandeur": _demandeur("Kamga", "Eric", "693000008"),
     "donnees": {"intitule_document": "Procuration bancaire", "signataire": {"nom": "Kamga", "prenom": "Eric"},
                 "qualite_signataire": "Mandant", "nombre_exemplaires": 1}},
    {"type": "CERTIFICATION_CONFORME", "objet": "Certification conforme d'acte de naissance", "cible": Statut.ANNULE,
     "motif": "Demande retirée par le demandeur au guichet.", "pieces": [],
     "demandeur": _demandeur("Essomba", "Rose", "694000009"),
     "donnees": {"intitule_document": "Acte de naissance", "nombre_copies": 1}},
    {"type": "COPIE_ACTE", "objet": "Copie d'acte de décès pour succession", "cible": Statut.DELIVRE,
     "instructeur": "civil", "demandeur": _demandeur("Njoya", "Aïcha", "656000010", "aicha.njoya@example.cm"),
     "donnees": {"type_acte": "DECES", "numero_acte": "112/2024", "annee": 2024,
                 "centre_etat_civil": "Centre d'état civil de Douala IIe", "nombre_copies": 1,
                 "qualite_demandeur": "Fille du défunt"}},
]

ETAPES = [Statut.SOUMIS, Statut.EN_INSTRUCTION, Statut.EN_ATTENTE_DECISION, Statut.APPROUVE, Statut.DELIVRE]


def _courant(u: Utilisateur) -> UtilisateurCourant:
    return UtilisateurCourant(id=u.id, nom=u.nom, role=Role(u.role),
                              categorie=Categorie(u.categorie) if u.categorie else None)


async def creer_comptes(session: AsyncSession) -> dict[str, UtilisateurCourant]:
    resultat = {}
    for c in COMPTES:
        u = await session.scalar(select(Utilisateur).where(Utilisateur.identifiant == c.identifiant))
        if u is None:
            u = await auth.creer_utilisateur(session, UtilisateurCreation(
                nom=c.nom, identifiant=c.identifiant, mot_de_passe=c.mot_de_passe, role=c.role))
        resultat[c.identifiant] = _courant(u)
    return resultat


async def _amener(session_factory: async_sessionmaker[AsyncSession], agents: dict[str, UtilisateurCourant],
                  spec: dict[str, Any]) -> tuple[str, str, Statut]:
    """Fait avancer un dossier jusqu'au statut visé ; chaque opération a sa propre session, comme une requête."""

    async def op(fonction, *args):  # noqa: ANN001, ANN002, ANN202
        async with session_factory() as session:
            return await fonction(session, *args)

    accueil = agents["accueil"]
    dossier = await op(dossiers.creer, accueil, DossierCreation(
        type_demarche=spec["type"], objet=spec["objet"], demandeur=spec["demandeur"],
        donnees_specifiques=spec["donnees"]))
    dossier_id, reference, type_ = dossier.id, dossier.reference, dossier.type_demarche
    codes = [p.code for p in dossier.pieces_requises]
    a_declarer = spec.get("pieces")
    for code in codes:
        if a_declarer is None or code in a_declarer:
            await op(dossiers.declarer_piece, accueil, dossier_id, PieceDeclaration(
                code_piece=code, date_reception=date.today(), etat=EtatPiece.CONFORME))

    cible: Statut = spec["cible"]
    if cible == Statut.ANNULE:
        await op(dossiers.annuler, accueil, dossier_id, spec["motif"])
    if cible in (Statut.BROUILLON, Statut.ANNULE):
        return reference, type_, cible

    await op(dossiers.transition, accueil, dossier_id, Statut.SOUMIS, None, None)
    if cible == Statut.SOUMIS:
        return reference, type_, cible
    instructeur = agents[spec["instructeur"]]
    verification = await op(dossiers.verifier_completude, instructeur, dossier_id)
    if cible == Statut.INCOMPLET:
        assert not verification.complet
        return reference, type_, cible
    await op(dossiers.transition, instructeur, dossier_id, Statut.EN_INSTRUCTION, None, None)
    if cible == Statut.EN_INSTRUCTION:
        return reference, type_, cible
    await op(dossiers.transition, instructeur, dossier_id, Statut.EN_ATTENTE_DECISION, None,
             "Instruction terminée : pièces et identité vérifiées.")
    if cible == Statut.EN_ATTENTE_DECISION:
        return reference, type_, cible
    issue = IssueDecision.REJETE if cible == Statut.REJETE else IssueDecision.APPROUVE
    await op(dossiers.decider, agents["chef"], dossier_id, issue, spec.get("motif"))
    if cible == Statut.DELIVRE:
        await op(dossiers.transition, accueil, dossier_id, Statut.DELIVRE, None, "Document remis au demandeur.")
    return reference, type_, cible


async def peupler(session_factory: async_sessionmaker[AsyncSession], avec_dossiers: bool = True) -> dict[str, Any]:
    async with session_factory() as session:
        await demarches.initialiser_catalogue(session)
        await auth.creer_admin_initial(session, get_settings())
        agents = await creer_comptes(session)
        existants = int(await session.scalar(select(func.count()).select_from(Dossier)) or 0)
    crees = []
    if avec_dossiers and existants == 0:
        for spec in DOSSIERS:
            crees.append(await _amener(session_factory, agents, spec))
    return {"comptes": list(agents), "dossiers": crees, "dossiers_existants": existants}


def _afficher(resultat: dict[str, Any]) -> None:
    settings = get_settings()
    print("\nComptes de démonstration (mot de passe entre parenthèses) :")
    if settings.admin_identifiant:
        print(f"  {settings.admin_identifiant:<10} Administrateur      (ADMIN_MOT_DE_PASSE de votre .env)")
    for c in COMPTES:
        print(f"  {c.identifiant:<10} {c.nom:<18}  {c.role:<20} ({c.mot_de_passe})")
    if resultat["dossiers"]:
        print(f"\n{len(resultat['dossiers'])} dossiers créés :")
        for reference, type_, statut in resultat["dossiers"]:
            print(f"  {reference}  {type_:<24} {statut}")
    elif resultat["dossiers_existants"]:
        print(f"\nLa base contient déjà {resultat['dossiers_existants']} dossier(s) : aucun dossier ajouté.")
    print("\nOuvrez http://127.0.0.1:5000 et connectez-vous avec l'un de ces comptes.")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Charge les données de démonstration.")
    parser.add_argument("--sans-dossiers", action="store_true", help="crée seulement les comptes")
    args = parser.parse_args(argv)
    settings = get_settings()
    session_factory = init_engine(settings.database_url)
    try:
        resultat = await peupler(session_factory, avec_dossiers=not args.sans_dossiers)
    finally:
        await dispose_engine()
    _afficher(resultat)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
