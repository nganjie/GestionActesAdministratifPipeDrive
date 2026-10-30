"""Libellés d'affichage et styles des statuts (charte de la maquette)."""

STATUTS = {
    "BROUILLON": ("Brouillon", "statut-brouillon"),
    "SOUMIS": ("Soumis", "statut-soumis"),
    "INCOMPLET": ("Incomplet", "statut-incomplet"),
    "EN_INSTRUCTION": ("En instruction", "statut-instruction"),
    "EN_ATTENTE_DECISION": ("Attente décision", "statut-decision"),
    "APPROUVE": ("Approuvé", "statut-approuve"),
    "DELIVRE": ("Délivré", "statut-delivre"),
    "REJETE": ("Rejeté", "statut-rejete"),
    "ANNULE": ("Annulé", "statut-annule"),
}

ORDRE_CYCLE = ["BROUILLON", "SOUMIS", "EN_INSTRUCTION", "EN_ATTENTE_DECISION", "DECISION", "DELIVRE"]

SYNCHRO = {
    "SYNCHRONISE": ("Synchronisé", "sync-ok"),
    "EN_ATTENTE": ("En attente", "sync-attente"),
    "ECHEC": ("En échec", "sync-echec"),
    None: ("Non requis", "sync-aucun"),
}

ROLES = {
    "ACCUEIL": "Agent d'accueil",
    "AGENT_ETAT_CIVIL": "Agent d'état civil",
    "AGENT_CERTIFICATION": "Agent de certification",
    "RESPONSABLE": "Officier / responsable",
    "ADMIN": "Administrateur",
}

CATEGORIES = {"ETAT_CIVIL": "État civil", "CERTIFICATION": "Certification"}

ETATS_PIECE = {"CONFORME": "Conforme", "A_CORRIGER": "À corriger", "RETIREE": "Retirée"}

TYPES_EVENEMENT = {
    "CREATION": "Dossier créé",
    "MODIFICATION": "Brouillon modifié",
    "PIECE_DECLAREE": "Pièce déclarée",
    "PIECE_MISE_A_JOUR": "Pièce mise à jour",
    "TRANSITION": "Changement de statut",
    "BLOCAGE": "Dossier bloqué",
    "DECISION": "Décision",
    "ANNULATION": "Annulation",
}

OBJETS_SYNCHRO = {
    "PERSON": "Contact du demandeur", "MAJ_PERSON": "Mise à jour du contact", "DEAL": "Dossier (deal)",
    "DEAL_MAJ": "Étape du deal", "ACTIVITY": "Activité de suivi", "CLORE": "Clôture des activités",
}


def libelle_statut(code: str | None) -> str:
    return STATUTS.get(code or "", (code or "—", ""))[0]


def classe_statut(code: str | None) -> str:
    return STATUTS.get(code or "", ("", "statut-brouillon"))[1]
