"""Actions proposées selon le rôle et le statut (FRS §2.1, §4.2).

L'interface n'affiche que ce que l'utilisateur peut faire ; l'API reste l'arbitre et ses refus sont affichés.
"""

from dataclasses import dataclass

INSTRUCTEURS = {"AGENT_ETAT_CIVIL", "AGENT_CERTIFICATION"}
ANNULABLES = {"BROUILLON", "SOUMIS", "INCOMPLET", "EN_INSTRUCTION", "EN_ATTENTE_DECISION"}
STATUTS_PIECES = {"BROUILLON", "SOUMIS", "INCOMPLET"}


@dataclass(frozen=True)
class Action:
    libelle: str
    type: str  # transition | verification | decision | annulation | modification
    cible: str | None = None
    motif: bool = False
    principale: bool = False
    danger: bool = False


def actions_dossier(role: str, statut: str) -> list[Action]:
    actions: list[Action] = []
    instructeur = role in INSTRUCTEURS
    if statut == "BROUILLON" and role == "ACCUEIL":
        actions += [Action("Soumettre le dossier", "transition", "SOUMIS", principale=True),
                    Action("Modifier", "modification")]
    if statut in ("SOUMIS", "INCOMPLET") and instructeur:
        actions += [Action("Passer en instruction", "transition", "EN_INSTRUCTION", principale=True),
                    Action("Vérifier la complétude", "verification")]
    if statut == "SOUMIS" and instructeur:
        actions.append(Action("Bloquer : pièces à compléter", "transition", "INCOMPLET", motif=True))
    if statut == "EN_INSTRUCTION" and instructeur:
        actions.append(Action("Terminer l'instruction", "transition", "EN_ATTENTE_DECISION", principale=True))
    if statut == "EN_ATTENTE_DECISION" and role == "RESPONSABLE":
        actions.append(Action("Décider", "decision", principale=True))
    if statut == "APPROUVE" and (role in ("ACCUEIL", "RESPONSABLE") or instructeur):
        actions.append(Action("Enregistrer la délivrance", "transition", "DELIVRE", principale=True))
    if statut in ANNULABLES and role in ("ACCUEIL", "RESPONSABLE"):
        actions.append(Action("Annuler le dossier", "annulation", danger=True))
    return actions


def peut_declarer_pieces(role: str, statut: str) -> bool:
    return statut in STATUTS_PIECES and (role == "ACCUEIL" or role in INSTRUCTEURS)


def peut_creer(role: str) -> bool:
    return role == "ACCUEIL"


def est_admin(role: str) -> bool:
    return role == "ADMIN"


def file_de_travail(role: str) -> list[str]:
    """Statuts qui attendent une action de ce rôle (tableau de bord)."""
    return {
        "ACCUEIL": ["BROUILLON", "APPROUVE"],
        "AGENT_ETAT_CIVIL": ["SOUMIS", "INCOMPLET", "EN_INSTRUCTION"],
        "AGENT_CERTIFICATION": ["SOUMIS", "INCOMPLET", "EN_INSTRUCTION"],
        "RESPONSABLE": ["EN_ATTENTE_DECISION"],
    }.get(role, [])
