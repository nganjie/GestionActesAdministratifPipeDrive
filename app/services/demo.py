"""Réinitialisation de la démonstration (mode démo uniquement).

Base locale et Pipedrive repartent ensemble : les dossiers locaux sont effacés, les deals « ACT-… » du pipeline
configuré et leurs activités sont supprimés, puis les données de démonstration sont rechargées. Les comptes, la
configuration des démarches, les contacts Pipedrive et le journal technique sont conservés.

Exception assumée à RM07 (historique en ajout seul) : elle n'existe qu'avec MODE_DEMO=true.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AccesRefuse, RegleMetierViolee
from app.db.models import (
    Compteur,
    Decision,
    Demandeur,
    Dossier,
    DossierPieceRequise,
    EvenementHistorique,
    EvenementOutbox,
    ParametrePipedrive,
    PieceFournie,
    ReferenceSynchro,
)
from app.integrations.pipedrive.adapter import PipedriveAdapter
from app.integrations.pipedrive.errors import ErreurRelancable, RessourceAbsente
from app.scripts import seed_demo

CONFIRMATION = "REINITIALISER"
PREFIXE_DEAL = "ACT-"
_TENTATIVES = 3

# Ordre imposé par les clés étrangères.
_TABLES = (EvenementOutbox, ReferenceSynchro, EvenementHistorique, Decision, PieceFournie, DossierPieceRequise,
           Dossier, Demandeur, Compteur, ParametrePipedrive)


@dataclass
class Bilan:
    dossiers_supprimes: int
    deals_supprimes: int
    activites_supprimees: int
    dossiers_crees: int
    pipedrive: bool


def verifier_autorisation(settings: Settings, confirmation: str) -> None:
    if not settings.mode_demo:
        raise AccesRefuse("La réinitialisation n'est possible qu'en mode démonstration (MODE_DEMO=true).",
                          code="MODE_DEMO_INACTIF")
    if confirmation.strip() != CONFIRMATION:
        raise RegleMetierViolee(f"Saisissez exactement « {CONFIRMATION} » pour confirmer.",
                                code="CONFIRMATION_INVALIDE")


async def _avec_relance[T](appel: Callable[[], Awaitable[T]]) -> T:
    """Limite de débit ou panne passagère : quelques nouvelles tentatives (une suppression est idempotente)."""
    for tentative in range(1, _TENTATIVES + 1):
        try:
            return await appel()
        except ErreurRelancable as exc:
            if tentative == _TENTATIVES:
                raise
            await asyncio.sleep(min(exc.retry_after or 2 ** tentative, 10))
    raise AssertionError("inatteignable")


async def _supprimer(appel: Callable[[], Awaitable[None]]) -> bool:
    try:
        await _avec_relance(appel)
    except RessourceAbsente:
        return False
    return True


async def nettoyer_pipedrive(adapter: PipedriveAdapter, settings: Settings) -> tuple[int, int]:
    """Supprime les deals « ACT-… » du pipeline configuré et leurs activités ; rien d'autre n'est touché."""
    pipelines = await _avec_relance(adapter.lister_pipelines)
    pipeline_id = next((p["id"] for p in pipelines if p.get("name") == settings.pipedrive_pipeline_name), None)
    if pipeline_id is None:
        return 0, 0
    deals = [d for d in await _avec_relance(lambda: adapter.lister_deals_pipeline(pipeline_id))
             if str(d.get("title", "")).startswith(PREFIXE_DEAL) and d.get("pipeline_id", pipeline_id) == pipeline_id]
    nb_deals = nb_activites = 0
    for deal in deals:
        for activite in await _avec_relance(lambda d=deal: adapter.lister_activites_deal(d["id"])):
            nb_activites += await _supprimer(lambda a=activite: adapter.supprimer_activite(a["id"]))
        nb_deals += await _supprimer(lambda d=deal: adapter.supprimer_deal(d["id"]))
    return nb_deals, nb_activites


async def vider_base(session: AsyncSession) -> int:
    """Efface dossiers, demandeurs, synchronisations et compteurs ; conserve comptes, démarches et journal."""
    nombre = int(await session.scalar(select(func.count()).select_from(Dossier)) or 0)
    for table in _TABLES:
        await session.execute(delete(table))
    return nombre


async def reinitialiser(session_factory: async_sessionmaker[AsyncSession], settings: Settings,
                        adapter: PipedriveAdapter) -> Bilan:
    if settings.pipedrive_configure:
        # Échoue tôt (jeton refusé, Pipedrive injoignable) avant d'effacer quoi que ce soit.
        await _avec_relance(adapter.verifier_jeton)
    # La base d'abord : le worker n'a plus rien à envoyer pendant le nettoyage de Pipedrive.
    async with session_factory() as session:
        dossiers_supprimes = await vider_base(session)
        await session.commit()
    deals = activites = 0
    if settings.pipedrive_configure:
        deals, activites = await nettoyer_pipedrive(adapter, settings)
    resultat = await seed_demo.peupler(session_factory)
    return Bilan(dossiers_supprimes=dossiers_supprimes, deals_supprimes=deals, activites_supprimees=activites,
                 dossiers_crees=len(resultat["dossiers"]), pipedrive=settings.pipedrive_configure)
