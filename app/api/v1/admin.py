"""Démarches (UC16), synchronisations (UC15), journaux et santé (UC17), réinitialisation de la démo."""

import dataclasses
import uuid
from datetime import datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import text

from app.api.deps import Admin, Courant, Lecture, Session
from app.core.config import get_settings
from app.core.errors import PipedriveDelaiDepasse, PipedriveErreurApi, PipedriveIndisponible
from app.db.base import get_session_factory
from app.domain.enums import EtatSynchro
from app.integrations.pipedrive.errors import ErreurIndeterminee, ErreurRelancable, PipedriveErreur
from app.schemas.api import (
    DemarcheModification,
    DemarcheSortie,
    DemoBilanSortie,
    DemoEtatSortie,
    DemoReinitialisation,
    JournalSortie,
    Page,
    PieceRequiseCreation,
    PieceRequiseModification,
    ReferenceSynchroSortie,
    SantePipedriveSortie,
)
from app.services import demarches, demo, journal
from app.services import synchronisation as sync
from app.services.pipedrive_init import lire_parametres, types_activite_manquants

router = APIRouter()


# --- Démarches ------------------------------------------------------------------------------------------

@router.get("/demarches", response_model=list[DemarcheSortie], tags=["Démarches"],
            summary="Types de démarches et pièces requises")
async def lister_demarches(_: Courant, session: Session) -> list[DemarcheSortie]:
    return [DemarcheSortie.model_validate(d) for d in await demarches.lister(session)]


@router.patch("/admin/demarches/{code}", response_model=DemarcheSortie, tags=["Démarches"],
              summary="Modifier une démarche (UC16)")
async def modifier_demarche(code: str, donnees: DemarcheModification, _: Admin,
                            session: Session) -> DemarcheSortie:
    return DemarcheSortie.model_validate(await demarches.modifier(session, code, donnees))


@router.post("/admin/demarches/{code}/pieces", response_model=DemarcheSortie, tags=["Démarches"],
             status_code=status.HTTP_201_CREATED, summary="Ajouter une pièce requise (UC16)")
async def ajouter_piece(code: str, donnees: PieceRequiseCreation, _: Admin, session: Session) -> DemarcheSortie:
    return DemarcheSortie.model_validate(await demarches.ajouter_piece(session, code, donnees))


@router.patch("/admin/demarches/{code}/pieces/{piece_id}", response_model=DemarcheSortie, tags=["Démarches"],
              summary="Modifier ou désactiver une pièce requise (UC16)")
async def modifier_piece(code: str, piece_id: uuid.UUID, donnees: PieceRequiseModification, _: Admin,
                         session: Session) -> DemarcheSortie:
    return DemarcheSortie.model_validate(await demarches.modifier_piece(session, code, piece_id, donnees))


# --- Synchronisations ------------------------------------------------------------------------------------

@router.get("/synchronisations", response_model=Page[ReferenceSynchroSortie], tags=["Synchronisation"],
            summary="Lister les synchronisations (UC15)")
async def lister_synchronisations(
    _: Admin, session: Session, etat: EtatSynchro | None = None, dossier_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1), taille: int = Query(20, ge=1, le=100),
) -> Page[ReferenceSynchroSortie]:
    lignes, total = await sync.lister(session, etat=etat, dossier_id=dossier_id, page=page, taille=taille)
    return Page(elements=[ReferenceSynchroSortie.model_validate(r) for r in lignes], total=total, page=page,
                taille=taille)


@router.post("/synchronisations/relance-globale", tags=["Synchronisation"],
             status_code=status.HTTP_202_ACCEPTED, summary="Relancer toutes les synchronisations en échec")
async def relancer_tout(_: Admin, session: Session) -> dict[str, int]:
    return {"relancees": await sync.relancer_tout(session)}


@router.post("/synchronisations/{reference_id}/relance", response_model=ReferenceSynchroSortie,
             tags=["Synchronisation"], status_code=status.HTTP_202_ACCEPTED,
             summary="Relancer une synchronisation (UC15)")
async def relancer(reference_id: uuid.UUID, _: Admin, session: Session) -> ReferenceSynchroSortie:
    return ReferenceSynchroSortie.model_validate(await sync.relancer(session, reference_id))


# --- Journaux et santé -------------------------------------------------------------------------------------

@router.get("/admin/journaux", response_model=Page[JournalSortie], tags=["Administration"],
            summary="Journaux techniques (UC17)")
async def journaux(
    _: Admin, session: Session, niveau: str | None = None, operation: str | None = None,
    correlation_id: str | None = None, du: datetime | None = None, au: datetime | None = None,
    page: int = Query(1, ge=1), taille: int = Query(50, ge=1, le=200),
) -> Page[JournalSortie]:
    lignes, total = await journal.lister(session, niveau=niveau, operation=operation,
                                        correlation_id=correlation_id, du=du, au=au, page=page, taille=taille)
    return Page(elements=[JournalSortie.model_validate(j) for j in lignes], total=total, page=page, taille=taille)


@router.get("/admin/sante/pipedrive", response_model=SantePipedriveSortie, tags=["Administration"],
            summary="État de l'intégration Pipedrive (OP-01, OP-16)")
async def sante_pipedrive(_: Admin, session: Session, lecture: Lecture) -> SantePipedriveSortie:
    settings = get_settings()
    resultat = SantePipedriveSortie(
        configure=settings.pipedrive_configure, jeton_valide=None,
        pipeline_initialise=await lire_parametres(session) is not None,
        synchronisations=await sync.compter_par_etat(session),
    )
    if not settings.pipedrive_configure:
        return resultat
    try:
        compte = await lecture.adapter.verifier_jeton()
        resultat.jeton_valide = True
        resultat.compte_id = compte["id"]
        resultat.company_domain = compte["company_domain"]
        resultat.types_activite_manquants = await types_activite_manquants(lecture.adapter)
    except PipedriveErreur as exc:
        resultat.jeton_valide = False if exc.status == 401 else None
        resultat.erreur = exc.code
    finally:
        journal.ecrire_appels(session, lecture.appels)
        await session.commit()
    return resultat


# --- Démonstration ------------------------------------------------------------------------------------------

@router.get("/admin/demo", response_model=DemoEtatSortie, tags=["Administration"],
            summary="Mode démonstration actif ?")
async def etat_demo(_: Admin) -> DemoEtatSortie:
    settings = get_settings()
    return DemoEtatSortie(actif=settings.mode_demo, pipedrive=settings.pipedrive_configure,
                          pipeline=settings.pipedrive_pipeline_name)


@router.post("/admin/demo/reinitialiser", response_model=DemoBilanSortie, tags=["Administration"],
             summary="Réinitialiser la démonstration (MODE_DEMO=true uniquement)")
async def reinitialiser_demo(donnees: DemoReinitialisation, _: Admin, session: Session,
                             lecture: Lecture) -> DemoBilanSortie:
    settings = get_settings()
    demo.verifier_autorisation(settings, donnees.confirmation)
    try:
        bilan = await demo.reinitialiser(get_session_factory(), settings, lecture.adapter)
    except PipedriveErreur as exc:
        journal.ecrire(session, "DEMO_REINITIALISATION", "ECHEC", niveau="ERROR", code_erreur=exc.code)
        message = (f"Réinitialisation interrompue par Pipedrive ({exc.code}). "
                   "Relancez-la : elle peut être rejouée sans risque.")
        if isinstance(exc, ErreurIndeterminee):
            raise PipedriveDelaiDepasse(message) from exc
        if isinstance(exc, ErreurRelancable):
            raise PipedriveIndisponible(message) from exc
        raise PipedriveErreurApi(message, code=f"PIPEDRIVE_{exc.code}") from exc
    else:
        journal.ecrire(session, "DEMO_REINITIALISATION", "SUCCES",
                       detail=f"{bilan.dossiers_supprimes} dossier(s), {bilan.deals_supprimes} deal(s) et "
                              f"{bilan.activites_supprimees} activité(s) supprimés ; "
                              f"{bilan.dossiers_crees} dossier(s) recréés")
    finally:
        journal.ecrire_appels(session, lecture.appels)
        await session.commit()
    return DemoBilanSortie(**dataclasses.asdict(bilan))


@router.get("/sante", tags=["Administration"], summary="Santé de l'API (public)")
async def sante(session: Session) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"statut": "ok", "base": "ok"}
