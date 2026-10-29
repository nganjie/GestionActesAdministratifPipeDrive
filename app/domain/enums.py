"""Énumérations du domaine (FRS §2, §4, §6.1)."""

from enum import StrEnum


class Role(StrEnum):
    ACCUEIL = "ACCUEIL"
    AGENT_ETAT_CIVIL = "AGENT_ETAT_CIVIL"
    AGENT_CERTIFICATION = "AGENT_CERTIFICATION"
    RESPONSABLE = "RESPONSABLE"
    ADMIN = "ADMIN"


class Categorie(StrEnum):
    ETAT_CIVIL = "ETAT_CIVIL"
    CERTIFICATION = "CERTIFICATION"


# Catégorie implicite des rôles d'instruction (RM09 : périmètre par catégorie).
CATEGORIE_DU_ROLE: dict[Role, Categorie] = {
    Role.AGENT_ETAT_CIVIL: Categorie.ETAT_CIVIL,
    Role.AGENT_CERTIFICATION: Categorie.CERTIFICATION,
}

ROLES_INSTRUCTEURS = frozenset(CATEGORIE_DU_ROLE)


class Statut(StrEnum):
    BROUILLON = "BROUILLON"
    SOUMIS = "SOUMIS"
    INCOMPLET = "INCOMPLET"
    EN_INSTRUCTION = "EN_INSTRUCTION"
    EN_ATTENTE_DECISION = "EN_ATTENTE_DECISION"
    APPROUVE = "APPROUVE"
    REJETE = "REJETE"
    DELIVRE = "DELIVRE"
    ANNULE = "ANNULE"


STATUTS_TERMINAUX = frozenset({Statut.DELIVRE, Statut.REJETE, Statut.ANNULE})
STATUTS_ANNULABLES = frozenset({
    Statut.BROUILLON, Statut.SOUMIS, Statut.INCOMPLET, Statut.EN_INSTRUCTION, Statut.EN_ATTENTE_DECISION,
})


class EtatPiece(StrEnum):
    CONFORME = "CONFORME"
    A_CORRIGER = "A_CORRIGER"
    RETIREE = "RETIREE"


class IssueDecision(StrEnum):
    APPROUVE = "APPROUVE"
    REJETE = "REJETE"


class EtatSynchro(StrEnum):
    EN_ATTENTE = "EN_ATTENTE"
    SYNCHRONISE = "SYNCHRONISE"
    ECHEC = "ECHEC"


class TypePipedrive(StrEnum):
    PERSON = "person"
    DEAL = "deal"
    ACTIVITY = "activity"


class TypeEvenementSync(StrEnum):
    SYNC_DEMANDEUR = "SYNC_DEMANDEUR"
    MAJ_DEMANDEUR = "MAJ_DEMANDEUR"
    CREER_DEAL = "CREER_DEAL"
    MAJ_DEAL = "MAJ_DEAL"
    CREER_ACTIVITE = "CREER_ACTIVITE"
    CLORE_ACTIVITES = "CLORE_ACTIVITES"
