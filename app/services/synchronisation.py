"""File de synchronisation (outbox) et références de synchronisation (FRS RI02-RI04, UC13-UC15)."""

import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflit, RessourceIntrouvable
from app.core.logging import get_correlation_id
from app.db.base import maintenant
from app.db.models import Demandeur, Dossier, EvenementOutbox, ReferenceSynchro
from app.domain.enums import EtatSynchro, Statut, TypeEvenementSync, TypePipedrive
from app.domain.projection import ACTIVITE_PAR_STATUT, STATUTS_CLOTURANTS
from app.schemas.api import ObjetSynchroSortie, SynchronisationSortie
from app.services import journal


def cle_person(demandeur_id: uuid.UUID) -> str:
    return f"PERSON:{demandeur_id}"


def cle_deal(dossier_id: uuid.UUID) -> str:
    return f"DEAL:{dossier_id}"


async def enfiler(session: AsyncSession, *, type_: TypeEvenementSync, cle: str, objet_type: str,
                  objet_id: str, type_pipedrive: TypePipedrive, dossier_id: uuid.UUID | None = None,
                  demandeur_id: uuid.UUID | None = None, charge: dict[str, Any] | None = None) -> ReferenceSynchro:
    """Crée la référence EN_ATTENTE et l'événement outbox, dans la transaction métier en cours (idempotent)."""
    existante = await session.scalar(select(ReferenceSynchro).where(ReferenceSynchro.cle_idempotence == cle))
    if existante is not None:
        return existante
    ref = ReferenceSynchro(
        id=uuid.uuid4(), cle_idempotence=cle, objet_type=objet_type, objet_id=objet_id, dossier_id=dossier_id,
        type_pipedrive=type_pipedrive, etat=EtatSynchro.EN_ATTENTE, tentatives=0,
        prochaine_tentative=maintenant(), indetermine=False,
    )
    session.add(ref)
    session.add(EvenementOutbox(
        type=type_, reference_id=ref.id, dossier_id=dossier_id, demandeur_id=demandeur_id,
        charge=charge or {}, correlation_id=get_correlation_id(), traite=False,
    ))
    return ref


async def enfiler_demandeur(session: AsyncSession, demandeur: Demandeur) -> None:
    await enfiler(session, type_=TypeEvenementSync.SYNC_DEMANDEUR, cle=cle_person(demandeur.id),
                  objet_type="demandeur", objet_id=str(demandeur.id), type_pipedrive=TypePipedrive.PERSON,
                  demandeur_id=demandeur.id)


async def enfiler_maj_demandeur(session: AsyncSession, demandeur: Demandeur) -> None:
    await enfiler(session, type_=TypeEvenementSync.MAJ_DEMANDEUR, cle=f"MAJ_PERSON:{demandeur.id}:{uuid.uuid4()}",
                  objet_type="demandeur", objet_id=str(demandeur.id), type_pipedrive=TypePipedrive.PERSON,
                  demandeur_id=demandeur.id)


async def projeter_transition(session: AsyncSession, dossier: Dossier, ancien: Statut, nouveau: Statut,
                              numero_evenement: int) -> None:
    """Événements de synchronisation produits par un changement de statut (FRS §4.3)."""
    deal_existe = await session.scalar(
        select(ReferenceSynchro.id).where(ReferenceSynchro.cle_idempotence == cle_deal(dossier.id))
    )
    commun = {"dossier_id": dossier.id, "demandeur_id": dossier.demandeur_id}
    if ancien == Statut.BROUILLON and nouveau == Statut.SOUMIS:
        await enfiler(session, type_=TypeEvenementSync.CREER_DEAL, cle=cle_deal(dossier.id), objet_type="dossier",
                      objet_id=str(dossier.id), type_pipedrive=TypePipedrive.DEAL,
                      charge={"statut": nouveau}, **commun)
        deal_existe = True
    elif deal_existe:
        await enfiler(session, type_=TypeEvenementSync.MAJ_DEAL, cle=f"DEAL_MAJ:{dossier.id}:E{numero_evenement}",
                      objet_type="dossier", objet_id=str(dossier.id), type_pipedrive=TypePipedrive.DEAL,
                      charge={"statut": nouveau}, **commun)
    if not deal_existe:
        return  # dossier jamais soumis (annulation d'un brouillon) : rien à refléter
    activite = ACTIVITE_PAR_STATUT.get(nouveau)
    if activite is not None:
        await enfiler(session, type_=TypeEvenementSync.CREER_ACTIVITE,
                      cle=f"ACTIVITY:{dossier.id}:E{numero_evenement}", objet_type="evenement",
                      objet_id=f"{dossier.id}:E{numero_evenement}", type_pipedrive=TypePipedrive.ACTIVITY,
                      charge={"numero": numero_evenement, "libelle": activite.libelle, "type": activite.type,
                              "delai_jours": activite.delai_jours, "date": date.today().isoformat()},
                      **commun)
    if nouveau in STATUTS_CLOTURANTS:
        await enfiler(session, type_=TypeEvenementSync.CLORE_ACTIVITES,
                      cle=f"CLORE:{dossier.id}:E{numero_evenement}", objet_type="dossier",
                      objet_id=str(dossier.id), type_pipedrive=TypePipedrive.ACTIVITY, **commun)


def _pire_etat(etats: Iterable[str]) -> EtatSynchro | None:
    etats = set(etats)
    if not etats:
        return None
    if EtatSynchro.ECHEC in etats:
        return EtatSynchro.ECHEC
    if EtatSynchro.EN_ATTENTE in etats:
        return EtatSynchro.EN_ATTENTE
    return EtatSynchro.SYNCHRONISE


def _filtre_dossier(dossier_id: uuid.UUID, demandeur_id: uuid.UUID):  # noqa: ANN202
    return or_(
        ReferenceSynchro.dossier_id == dossier_id,
        (ReferenceSynchro.objet_type == "demandeur") & (ReferenceSynchro.objet_id == str(demandeur_id)),
    )


async def etat_dossier(session: AsyncSession, dossier: Dossier) -> SynchronisationSortie:
    refs = list(await session.scalars(
        select(ReferenceSynchro).where(_filtre_dossier(dossier.id, dossier.demandeur_id))
        .order_by(ReferenceSynchro.cree_le)
    ))
    return SynchronisationSortie(
        etat=_pire_etat(r.etat for r in refs),
        objets=[ObjetSynchroSortie(
            id=r.id, type=r.type_pipedrive, objet=r.cle_idempotence.split(":")[0], etat=EtatSynchro(r.etat),
            id_pipedrive=r.id_pipedrive, tentatives=r.tentatives, code_erreur=r.code_erreur,
            derniere_erreur=r.derniere_erreur,
            prochaine_tentative=r.prochaine_tentative if r.etat == EtatSynchro.EN_ATTENTE else None,
        ) for r in refs],
    )


async def etats_par_dossier(session: AsyncSession, dossiers: list[Dossier]) -> dict[uuid.UUID, EtatSynchro | None]:
    if not dossiers:
        return {}
    ids = [d.id for d in dossiers]
    demandeurs = {str(d.demandeur_id) for d in dossiers}
    lignes = await session.execute(
        select(ReferenceSynchro.dossier_id, ReferenceSynchro.objet_type, ReferenceSynchro.objet_id,
               ReferenceSynchro.etat)
        .where(or_(ReferenceSynchro.dossier_id.in_(ids),
                   (ReferenceSynchro.objet_type == "demandeur") & ReferenceSynchro.objet_id.in_(demandeurs)))
    )
    par_dossier: dict[uuid.UUID, list[str]] = {d.id: [] for d in dossiers}
    par_demandeur: dict[str, list[str]] = {}
    for dossier_id, objet_type, objet_id, etat in lignes:
        if dossier_id is not None:
            par_dossier.setdefault(dossier_id, []).append(etat)
        elif objet_type == "demandeur":
            par_demandeur.setdefault(objet_id, []).append(etat)
    return {d.id: _pire_etat(par_dossier[d.id] + par_demandeur.get(str(d.demandeur_id), [])) for d in dossiers}


async def lister(session: AsyncSession, *, etat: EtatSynchro | None, dossier_id: uuid.UUID | None,
                 page: int, taille: int) -> tuple[list[ReferenceSynchro], int]:
    requete = select(ReferenceSynchro)
    if etat:
        requete = requete.where(ReferenceSynchro.etat == etat)
    if dossier_id:
        requete = requete.where(ReferenceSynchro.dossier_id == dossier_id)
    total = await session.scalar(select(func.count()).select_from(requete.subquery()))
    lignes = await session.scalars(
        requete.order_by(ReferenceSynchro.maj_le.desc()).offset((page - 1) * taille).limit(taille)
    )
    return list(lignes), int(total or 0)


async def relancer(session: AsyncSession, reference_id: uuid.UUID) -> ReferenceSynchro:
    ref = await session.get(ReferenceSynchro, reference_id)
    if ref is None:
        raise RessourceIntrouvable()
    if ref.etat == EtatSynchro.SYNCHRONISE:
        raise Conflit("Cette synchronisation est déjà effectuée.", code="ETAT_INCOMPATIBLE")
    ref.etat = EtatSynchro.EN_ATTENTE
    ref.tentatives = 0
    ref.prochaine_tentative = maintenant()
    journal.ecrire(session, "SYNC_RELANCE", "SUCCES", detail=ref.cle_idempotence.split(":")[0])
    await session.commit()
    return ref


async def relancer_tout(session: AsyncSession) -> int:
    resultat = await session.execute(
        update(ReferenceSynchro).where(ReferenceSynchro.etat == EtatSynchro.ECHEC)
        .values(etat=EtatSynchro.EN_ATTENTE, tentatives=0, prochaine_tentative=maintenant())
    )
    journal.ecrire(session, "SYNC_RELANCE_GLOBALE", "SUCCES", detail=f"{resultat.rowcount} relance(s)")
    await session.commit()
    return int(resultat.rowcount or 0)


async def compter_par_etat(session: AsyncSession) -> dict[str, int]:
    lignes = await session.execute(
        select(ReferenceSynchro.etat, func.count()).group_by(ReferenceSynchro.etat)
    )
    compte = {e.value: 0 for e in EtatSynchro}
    for etat, n in lignes:
        compte[etat] = n
    return compte
