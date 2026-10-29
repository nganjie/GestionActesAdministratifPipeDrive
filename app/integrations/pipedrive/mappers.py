"""Transformation des objets internes en charges Pipedrive, avec minimisation (ISD §5, FRS RI05)."""

from typing import Any

# Seuls champs autorisés par type d'objet (vérifiés par les tests de minimisation, ISD-T13).
CHAMPS_AUTORISES = {
    "person": {"name", "owner_id", "emails", "phones"},
    "deal": {"title", "person_id", "pipeline_id", "stage_id", "owner_id", "status", "lost_reason"},
    "activity": {"subject", "type", "due_date", "deal_id", "participants", "owner_id", "note", "done"},
}


def _avec_proprietaire(charge: dict[str, Any], owner_id: int | None) -> dict[str, Any]:
    if owner_id is not None:
        charge["owner_id"] = owner_id
    return charge


def charge_personne(nom: str, prenom: str, email: str | None, telephone: str | None,
                    owner_id: int | None) -> dict[str, Any]:
    charge: dict[str, Any] = {"name": f"{prenom} {nom.upper()}"}
    if email:
        charge["emails"] = [{"value": email.lower(), "primary": True, "label": "work"}]
    if telephone:
        charge["phones"] = [{"value": telephone, "primary": True, "label": "mobile"}]
    return _avec_proprietaire(charge, owner_id)


def titre_deal(reference: str, libelle_demarche: str) -> str:
    return f"{reference} — {libelle_demarche}"


def charge_deal(reference: str, libelle_demarche: str, person_id: int, pipeline_id: int, stage_id: int,
                owner_id: int | None) -> dict[str, Any]:
    charge = {
        "title": titre_deal(reference, libelle_demarche),
        "person_id": person_id,
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
    }
    return _avec_proprietaire(charge, owner_id)


def charge_activite(sujet: str, type_: str, echeance: str, deal_id: int, person_id: int | None,
                    reference: str, owner_id: int | None) -> dict[str, Any]:
    charge: dict[str, Any] = {
        "subject": sujet,
        "type": type_,
        "due_date": echeance,
        "deal_id": deal_id,
        "note": f"Dossier {reference} — suivi automatique",
    }
    if person_id is not None:
        charge["participants"] = [{"person_id": person_id, "primary": True}]
    return _avec_proprietaire(charge, owner_id)
