"""Projection des événements métier vers Pipedrive (FRS §4.3, ISD §5.4).

Le module métier reste la source de vérité ; cette table décrit seulement le miroir.
"""

from dataclasses import dataclass

from app.domain.enums import Statut

# Étapes du pipeline, dans l'ordre (ISD §5.4).
ETAPES_PIPELINE: tuple[tuple[Statut, str], ...] = (
    (Statut.SOUMIS, "Reçu"),
    (Statut.INCOMPLET, "Pièces à compléter"),
    (Statut.EN_INSTRUCTION, "En instruction"),
    (Statut.EN_ATTENTE_DECISION, "En attente de décision"),
    (Statut.APPROUVE, "Approuvé"),
    (Statut.DELIVRE, "Délivré"),
)

LOST_REASON = {
    Statut.REJETE: "Dossier rejeté",
    Statut.ANNULE: "Dossier annulé",
}


@dataclass(frozen=True)
class ActiviteProjetee:
    libelle: str
    type: str  # clé Pipedrive : task, call, deadline
    delai_jours: int


ACTIVITE_PAR_STATUT: dict[Statut, ActiviteProjetee] = {
    Statut.SOUMIS: ActiviteProjetee("Vérifier les pièces", "task", 2),
    Statut.INCOMPLET: ActiviteProjetee("Relancer le demandeur : pièces manquantes", "call", 3),
    Statut.EN_INSTRUCTION: ActiviteProjetee("Instruire le dossier", "task", 5),
    Statut.EN_ATTENTE_DECISION: ActiviteProjetee("Décision attendue", "deadline", 3),
    Statut.APPROUVE: ActiviteProjetee("Préparer la remise au demandeur", "task", 2),
    Statut.REJETE: ActiviteProjetee("Informer le demandeur de la décision", "call", 1),
}

# Statuts dont l'entrée clôt les activités ouvertes du dossier.
STATUTS_CLOTURANTS = frozenset({Statut.DELIVRE, Statut.ANNULE})

TYPES_ACTIVITE_REQUIS = frozenset(a.type for a in ACTIVITE_PAR_STATUT.values())


def marqueur(reference: str, numero_evenement: int) -> str:
    return f"[{reference}·E{numero_evenement}]"


def sujet_activite(reference: str, numero_evenement: int, libelle: str) -> str:
    return f"{marqueur(reference, numero_evenement)} {libelle}"


def retirer_marqueur(sujet: str) -> str:
    if sujet.startswith("[") and "] " in sujet:
        return sujet.split("] ", 1)[1]
    return sujet
