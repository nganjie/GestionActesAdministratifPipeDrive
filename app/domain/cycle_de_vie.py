"""Machine à états du dossier (FRS §4.2, AF §7.2) et règles d'accès associées (RM04, RM09)."""

from dataclasses import dataclass

from app.domain.enums import CATEGORIE_DU_ROLE, Categorie, Role, Statut


@dataclass(frozen=True)
class RegleTransition:
    depuis: frozenset[Statut]
    vers: Statut
    roles: frozenset[Role]
    motif_obligatoire: bool = False
    pieces_completes: bool = False
    instruction: bool = False  # l'agent devient l'instructeur du dossier


_INSTRUCTEURS = frozenset({Role.AGENT_ETAT_CIVIL, Role.AGENT_CERTIFICATION})

# Transitions accessibles par POST /dossiers/{id}/transitions.
# APPROUVE/REJETE passent par /decision (UC10), ANNULE par /annulation (UC12).
TRANSITIONS: tuple[RegleTransition, ...] = (
    RegleTransition(frozenset({Statut.BROUILLON}), Statut.SOUMIS, frozenset({Role.ACCUEIL})),
    RegleTransition(frozenset({Statut.SOUMIS}), Statut.INCOMPLET, _INSTRUCTEURS,
                    motif_obligatoire=True, instruction=True),
    RegleTransition(frozenset({Statut.SOUMIS, Statut.INCOMPLET}), Statut.EN_INSTRUCTION, _INSTRUCTEURS,
                    pieces_completes=True, instruction=True),
    RegleTransition(frozenset({Statut.EN_INSTRUCTION}), Statut.EN_ATTENTE_DECISION, _INSTRUCTEURS,
                    instruction=True),
    RegleTransition(frozenset({Statut.APPROUVE}), Statut.DELIVRE,
                    _INSTRUCTEURS | {Role.ACCUEIL, Role.RESPONSABLE}),
)

STATUTS_PAR_DECISION = frozenset({Statut.APPROUVE, Statut.REJETE})


def trouver_transition(depuis: Statut, vers: Statut) -> RegleTransition | None:
    for regle in TRANSITIONS:
        if regle.vers == vers and depuis in regle.depuis:
            return regle
    return None


def peut_acceder(role: Role, categorie_utilisateur: Categorie | None, categorie_dossier: Categorie) -> bool:
    """Périmètre de consultation : un instructeur ne voit que sa catégorie (FRS §2.1)."""
    if role in CATEGORIE_DU_ROLE:
        return (categorie_utilisateur or CATEGORIE_DU_ROLE[role]) == categorie_dossier
    return True


def role_autorise(regle: RegleTransition, role: Role) -> bool:
    return role in regle.roles
