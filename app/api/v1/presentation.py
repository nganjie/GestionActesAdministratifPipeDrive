"""Construction des réponses normalisées (CDC EF06)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dossier, Utilisateur
from app.domain.enums import EtatSynchro
from app.schemas.api import (
    DecisionSortie,
    DemandeurSortie,
    DossierResume,
    DossierSortie,
    PieceFournieSortie,
    PieceRequiseDossierSortie,
)
from app.services import synchronisation as sync


async def noms_utilisateurs(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    lignes = await session.execute(select(Utilisateur.id, Utilisateur.nom).where(Utilisateur.id.in_(ids)))
    return {i: nom for i, nom in lignes}


async def dossier_complet(session: AsyncSession, d: Dossier) -> DossierSortie:
    relations = ["pieces_fournies", "pieces_requises", "decision", "demandeur", "demarche"]
    await session.refresh(d, attribute_names=relations)
    noms = await noms_utilisateurs(session, {d.createur_id, d.instructeur_id,
                                             d.decision.auteur_id if d.decision else None})
    decision = None
    if d.decision:
        decision = DecisionSortie.model_validate(d.decision).model_copy(
            update={"auteur_nom": noms.get(d.decision.auteur_id)})
    return DossierSortie(
        id=d.id, reference=d.reference, type_demarche=d.type_demarche, libelle_demarche=d.demarche.libelle,
        categorie=d.categorie, statut=d.statut, objet=d.objet, donnees_specifiques=d.donnees_specifiques,
        demandeur=DemandeurSortie.model_validate(d.demandeur), createur_id=d.createur_id,
        createur_nom=noms.get(d.createur_id), instructeur_id=d.instructeur_id,
        instructeur_nom=noms.get(d.instructeur_id) if d.instructeur_id else None,
        pieces_requises=[PieceRequiseDossierSortie.model_validate(p) for p in d.pieces_requises],
        pieces_fournies=[PieceFournieSortie.model_validate(p) for p in d.pieces_fournies],
        decision=decision,
        synchronisation=await sync.etat_dossier(session, d),
        version=d.version, cree_le=d.cree_le, maj_le=d.maj_le,
    )


def dossier_resume(d: Dossier, etat: EtatSynchro | None) -> DossierResume:
    return DossierResume(
        id=d.id, reference=d.reference, type_demarche=d.type_demarche, libelle_demarche=d.demarche.libelle,
        categorie=d.categorie, statut=d.statut, demandeur=f"{d.demandeur.prenom} {d.demandeur.nom}",
        instructeur_id=d.instructeur_id, synchronisation=etat, maj_le=d.maj_le,
    )
