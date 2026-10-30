"""Dossiers (FRS UC03 à UC12)."""

import uuid
from datetime import date

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import Courant, Lecture, Session
from app.api.v1.presentation import dossier_complet, dossier_resume, noms_utilisateurs
from app.db.models import ReferenceSynchro
from app.domain.enums import Categorie, EtatSynchro, Statut
from app.domain.projection import retirer_marqueur
from app.integrations.pipedrive.errors import PipedriveErreur
from app.schemas.api import (
    ActiviteSortie,
    ActivitesSortie,
    AnnulationEntree,
    DecisionEntree,
    DossierCreation,
    DossierModification,
    DossierResume,
    DossierSortie,
    EvenementHistoriqueSortie,
    Page,
    PieceDeclaration,
    PieceFournieSortie,
    PieceMiseAJour,
    SynchronisationSortie,
    TransitionEntree,
    VerificationSortie,
)
from app.services import dossiers, journal
from app.services import synchronisation as sync

router = APIRouter(prefix="/dossiers", tags=["Dossiers"])


@router.post("", response_model=DossierSortie, status_code=status.HTTP_201_CREATED,
             summary="Créer un dossier (UC03)")
async def creer(donnees: DossierCreation, courant: Courant, session: Session) -> DossierSortie:
    return await dossier_complet(session, await dossiers.creer(session, courant, donnees))


@router.get("", response_model=Page[DossierResume], summary="Rechercher et lister les dossiers (UC05)")
async def lister(
    courant: Courant, session: Session,
    statut: Statut | None = None, type: str | None = Query(None, alias="type"),
    categorie: Categorie | None = None, reference: str | None = None, demandeur: str | None = None,
    cree_du: date | None = None, cree_au: date | None = None,
    page: int = Query(1, ge=1), taille: int = Query(20, ge=1, le=100),
) -> Page[DossierResume]:
    elements, total = await dossiers.lister(
        session, courant, statut=statut, type_demarche=type, categorie=categorie, reference=reference,
        demandeur=demandeur, cree_du=cree_du, cree_au=cree_au, page=page, taille=taille,
    )
    etats = await sync.etats_par_dossier(session, elements)
    return Page(elements=[dossier_resume(d, etats.get(d.id)) for d in elements], total=total, page=page,
                taille=taille)


@router.get("/{dossier_id}", response_model=DossierSortie, summary="Consulter un dossier (UC04)")
async def obtenir(dossier_id: uuid.UUID, courant: Courant, session: Session) -> DossierSortie:
    return await dossier_complet(session, await dossiers.charger(session, dossier_id, courant))


@router.patch("/{dossier_id}", response_model=DossierSortie, summary="Modifier un brouillon (UC06)")
async def modifier(dossier_id: uuid.UUID, donnees: DossierModification, courant: Courant,
                   session: Session) -> DossierSortie:
    return await dossier_complet(session, await dossiers.modifier(session, courant, dossier_id, donnees))


@router.get("/{dossier_id}/pieces", response_model=list[PieceFournieSortie], summary="Pièces déclarées")
async def lister_pieces(dossier_id: uuid.UUID, courant: Courant, session: Session) -> list[PieceFournieSortie]:
    dossier = await dossiers.charger(session, dossier_id, courant)
    return [PieceFournieSortie.model_validate(p) for p in dossier.pieces_fournies]


@router.post("/{dossier_id}/pieces", response_model=PieceFournieSortie, status_code=status.HTTP_201_CREATED,
             summary="Déclarer une pièce (UC07)")
async def declarer_piece(dossier_id: uuid.UUID, donnees: PieceDeclaration, courant: Courant,
                         session: Session) -> PieceFournieSortie:
    return PieceFournieSortie.model_validate(await dossiers.declarer_piece(session, courant, dossier_id, donnees))


@router.patch("/{dossier_id}/pieces/{piece_id}", response_model=PieceFournieSortie,
              summary="Mettre à jour une pièce (UC07)")
async def maj_piece(dossier_id: uuid.UUID, piece_id: uuid.UUID, donnees: PieceMiseAJour, courant: Courant,
                    session: Session) -> PieceFournieSortie:
    return PieceFournieSortie.model_validate(
        await dossiers.maj_piece(session, courant, dossier_id, piece_id, donnees)
    )


@router.post("/{dossier_id}/verification-completude", response_model=VerificationSortie,
             summary="Vérifier la complétude (UC08)")
async def verifier(dossier_id: uuid.UUID, courant: Courant, session: Session) -> VerificationSortie:
    return await dossiers.verifier_completude(session, courant, dossier_id)


@router.post("/{dossier_id}/transitions", response_model=DossierSortie, summary="Changer le statut (UC09)")
async def transition(dossier_id: uuid.UUID, donnees: TransitionEntree, courant: Courant,
                     session: Session) -> DossierSortie:
    dossier = await dossiers.transition(session, courant, dossier_id, donnees.statut_cible, donnees.motif,
                                        donnees.commentaire)
    return await dossier_complet(session, dossier)


@router.post("/{dossier_id}/decision", response_model=DossierSortie, summary="Décider (UC10)")
async def decision(dossier_id: uuid.UUID, donnees: DecisionEntree, courant: Courant,
                   session: Session) -> DossierSortie:
    dossier = await dossiers.decider(session, courant, dossier_id, donnees.issue, donnees.motif)
    return await dossier_complet(session, dossier)


@router.post("/{dossier_id}/annulation", response_model=DossierSortie, summary="Annuler (UC12)")
async def annulation(dossier_id: uuid.UUID, donnees: AnnulationEntree, courant: Courant,
                     session: Session) -> DossierSortie:
    return await dossier_complet(session, await dossiers.annuler(session, courant, dossier_id, donnees.motif))


@router.get("/{dossier_id}/historique", response_model=list[EvenementHistoriqueSortie],
            summary="Consulter l'historique (UC11)")
async def historique(dossier_id: uuid.UUID, courant: Courant,
                     session: Session) -> list[EvenementHistoriqueSortie]:
    evenements = await dossiers.historique(session, courant, dossier_id)
    noms = await noms_utilisateurs(session, {e.auteur_id for e in evenements})
    return [EvenementHistoriqueSortie.model_validate(e).model_copy(update={"auteur_nom": noms.get(e.auteur_id)})
            for e in evenements]


@router.get("/{dossier_id}/synchronisation", response_model=SynchronisationSortie,
            summary="État de synchronisation Pipedrive")
async def synchronisation(dossier_id: uuid.UUID, courant: Courant, session: Session) -> SynchronisationSortie:
    return await sync.etat_dossier(session, await dossiers.charger(session, dossier_id, courant))


@router.get("/{dossier_id}/activites", response_model=ActivitesSortie,
            summary="Activités Pipedrive du dossier (UC04, OP-13)")
async def activites(dossier_id: uuid.UUID, courant: Courant, session: Session,
                    lecture: Lecture) -> ActivitesSortie:
    dossier = await dossiers.charger(session, dossier_id, courant)
    ligne = (await session.execute(
        select(ReferenceSynchro.id_pipedrive, ReferenceSynchro.etat)
        .where(ReferenceSynchro.cle_idempotence == sync.cle_deal(dossier.id))
    )).first()
    deal = ligne[0] if ligne and ligne[1] == EtatSynchro.SYNCHRONISE else None
    if deal is None:
        return ActivitesSortie(disponible=True, raison="NON_SYNCHRONISE", elements=[])
    try:
        brutes = await lecture.adapter.lister_activites_deal(deal)
    except PipedriveErreur as exc:
        return ActivitesSortie(disponible=False, raison=exc.code)
    finally:
        journal.ecrire_appels(session, lecture.appels)
        await session.commit()
    return ActivitesSortie(disponible=True, elements=[
        ActiviteSortie(id_externe=a["id"], intitule=retirer_marqueur(str(a.get("subject", ""))),
                       type=a.get("type"), echeance=a.get("due_date"), terminee=bool(a.get("done")))
        for a in brutes
    ])
