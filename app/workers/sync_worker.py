"""Worker de synchronisation vers Pipedrive (FRS UC13, UC14 ; ISD §4.3, §7.3).

Lancement : `python -m app.workers.sync_worker`
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.config import Settings, get_settings
from app.core.logging import configurer_logging, correlation_id_var
from app.db.base import init_engine, maintenant
from app.db.models import Demandeur, Dossier, EvenementOutbox, ReferenceSynchro
from app.domain.enums import EtatSynchro, Statut, TypeEvenementSync
from app.domain.projection import LOST_REASON, marqueur, sujet_activite
from app.integrations.pipedrive import mappers
from app.integrations.pipedrive.adapter import PipedriveAdapter
from app.integrations.pipedrive.client import AppelPipedrive, PipedriveClient
from app.integrations.pipedrive.errors import PipedriveErreur, RessourceAbsente
from app.services import journal
from app.services.pipedrive_init import obtenir_parametres
from app.services.synchronisation import cle_deal, cle_person

logger = logging.getLogger("app.sync")

DELAI_MAX = 300.0
DELAI_DEPENDANCE = 5.0


class EnAttenteDependance(Exception):
    """L'objet dont dépend l'événement n'est pas encore synchronisé : on réessaie sans compter de tentative."""


def delai_relance(tentative: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, DELAI_MAX)
    return min(2.0 ** tentative, DELAI_MAX) + random.uniform(0, 1)


class SyncWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings,
                 fabrique_adapter: Callable[[Callable[[AppelPipedrive], None]], PipedriveAdapter] | None = None):
        self.session_factory = session_factory
        self.settings = settings
        self._fabrique = fabrique_adapter or (
            lambda on_appel: PipedriveAdapter(PipedriveClient(settings, on_appel=on_appel))
        )

    # --- Boucle ------------------------------------------------------------------------------------

    async def executer(self, arret: asyncio.Event | None = None) -> None:
        arret = arret or asyncio.Event()
        logger.info("worker de synchronisation démarré")
        while not arret.is_set():
            try:
                traites = await self.traiter_lot()
            except Exception:
                logger.exception("erreur inattendue du worker")
                traites = 0
            if traites == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(arret.wait(), timeout=self.settings.sync_poll_interval)

    async def traiter_lot(self, limite: int = 20) -> int:
        """Traite au plus `limite` événements échus ; renvoie le nombre traité."""
        traites = 0
        exclus: set[int] = set()
        while traites < limite:
            async with self.session_factory() as session:
                evenement = await self._prochain(session, exclus)
                if evenement is None:
                    return traites
                exclus.add(evenement.id)
                await self._traiter(session, evenement)
                await session.commit()
                traites += 1
        return traites

    async def _prochain(self, session: AsyncSession, exclus: set[int]) -> EvenementOutbox | None:
        anterieur = aliased(EvenementOutbox)
        bloque = (
            select(anterieur.id)
            .where(and_(anterieur.dossier_id == EvenementOutbox.dossier_id, anterieur.id < EvenementOutbox.id,
                        anterieur.traite.is_(False)))
            .exists()
        )
        requete = (
            select(EvenementOutbox)
            .join(ReferenceSynchro, EvenementOutbox.reference_id == ReferenceSynchro.id)
            .where(EvenementOutbox.traite.is_(False), ReferenceSynchro.etat == EtatSynchro.EN_ATTENTE,
                   ReferenceSynchro.prochaine_tentative <= maintenant(), ~bloque)
            .order_by(EvenementOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=EvenementOutbox)
        )
        if exclus:
            requete = requete.where(EvenementOutbox.id.not_in(exclus))
        return await session.scalar(requete)

    # --- Traitement d'un événement -----------------------------------------------------------------

    async def _traiter(self, session: AsyncSession, evt: EvenementOutbox) -> None:
        ref = evt.reference
        appels: list[AppelPipedrive] = []
        adapter = self._fabrique(appels.append)
        jeton = correlation_id_var.set(evt.correlation_id)
        tentative = ref.tentatives + 1
        try:
            gestionnaire = self._gestionnaires()[TypeEvenementSync(evt.type)]
            ref.id_pipedrive = await gestionnaire(session, adapter, evt, ref)
            ref.etat = EtatSynchro.SYNCHRONISE
            ref.indetermine = False
            ref.code_erreur = ref.derniere_erreur = None
            evt.traite = True
        except EnAttenteDependance as exc:
            ref.prochaine_tentative = maintenant() + timedelta(seconds=DELAI_DEPENDANCE)
            ref.code_erreur, ref.derniere_erreur = "EN_ATTENTE_DEPENDANCE", str(exc)[:300]
        except PipedriveErreur as exc:
            ref.code_erreur, ref.derniere_erreur = exc.code, exc.message[:300]
            if exc.relancable and tentative < self.settings.pipedrive_max_retries:
                ref.tentatives = tentative
                ref.indetermine = ref.indetermine or exc.indetermine
                ref.prochaine_tentative = maintenant() + timedelta(seconds=delai_relance(tentative,
                                                                                        exc.retry_after))
            else:
                ref.tentatives = tentative
                ref.indetermine = ref.indetermine or exc.indetermine
                ref.etat = EtatSynchro.ECHEC
                journal.ecrire(session, f"SYNC_{evt.type}", "ECHEC", niveau="ERROR", code_erreur=exc.code,
                               tentative=tentative, detail="relance manuelle requise (UC15)")
        finally:
            journal.ecrire_appels(session, appels, tentative)
            correlation_id_var.reset(jeton)
            await adapter.client.aclose()

    def _gestionnaires(self) -> dict[TypeEvenementSync, Callable[..., Awaitable[int | None]]]:
        return {
            TypeEvenementSync.SYNC_DEMANDEUR: self._sync_demandeur,
            TypeEvenementSync.MAJ_DEMANDEUR: self._maj_demandeur,
            TypeEvenementSync.CREER_DEAL: self._creer_deal,
            TypeEvenementSync.MAJ_DEAL: self._maj_deal,
            TypeEvenementSync.CREER_ACTIVITE: self._creer_activite,
            TypeEvenementSync.CLORE_ACTIVITES: self._clore_activites,
        }

    # --- Outils ------------------------------------------------------------------------------------

    async def _ref_synchronisee(self, session: AsyncSession, cle: str) -> ReferenceSynchro:
        ref = await session.scalar(select(ReferenceSynchro).where(ReferenceSynchro.cle_idempotence == cle))
        if ref is None or ref.etat != EtatSynchro.SYNCHRONISE or ref.id_pipedrive is None:
            raise EnAttenteDependance(f"{cle.split(':')[0]} non synchronisé")
        return ref

    def _charge_personne(self, d: Demandeur) -> dict:
        return mappers.charge_personne(d.nom, d.prenom, d.email, d.telephone, self.settings.pipedrive_owner_id)

    async def _chercher_personne(self, adapter: PipedriveAdapter, d: Demandeur) -> int | None:
        for terme, champ in ((d.email, "email"), (d.telephone, "phone")):
            if terme:
                ids = await adapter.rechercher_personne(terme, champ)
                if ids:
                    return ids[0]
        return None

    async def _creer_deal_pour(self, session: AsyncSession, adapter: PipedriveAdapter, dossier: Dossier,
                               statut: Statut) -> int:
        person = await self._ref_synchronisee(session, cle_person(dossier.demandeur_id))
        params = await obtenir_parametres(session, adapter, self.settings)
        stage_id = params.etapes.get(statut, params.etapes[Statut.SOUMIS])
        return await adapter.creer_deal(mappers.charge_deal(
            dossier.reference, dossier.demarche.libelle, person.id_pipedrive, params.pipeline_id, stage_id,
            self.settings.pipedrive_owner_id,
        ))

    # --- Gestionnaires -----------------------------------------------------------------------------

    async def _sync_demandeur(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        demandeur = await session.get(Demandeur, evt.demandeur_id)
        # OP-02 toujours avant OP-03 : évite les doublons, y compris après un résultat indéterminé.
        existant = await self._chercher_personne(adapter, demandeur)
        if existant is not None:
            return existant
        return await adapter.creer_personne(self._charge_personne(demandeur))

    async def _maj_demandeur(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        demandeur = await session.get(Demandeur, evt.demandeur_id)
        person = await self._ref_synchronisee(session, cle_person(demandeur.id))
        try:
            await adapter.maj_personne(person.id_pipedrive, self._charge_personne(demandeur))
        except RessourceAbsente:
            logger.warning("contact supprimé dans Pipedrive : recréation (RI08)")
            person.id_pipedrive = (await self._chercher_personne(adapter, demandeur)
                                   or await adapter.creer_personne(self._charge_personne(demandeur)))
        return person.id_pipedrive

    async def _creer_deal(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        dossier = await session.get(Dossier, evt.dossier_id)
        if ref.indetermine:
            trouve = await adapter.rechercher_deal(dossier.reference)
            if trouve is not None:
                return trouve
        return await self._creer_deal_pour(session, adapter, dossier, Statut(evt.charge["statut"]))

    async def _maj_deal(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        dossier = await session.get(Dossier, evt.dossier_id)
        deal = await self._ref_synchronisee(session, cle_deal(dossier.id))
        statut = Statut(evt.charge["statut"])
        params = await obtenir_parametres(session, adapter, self.settings)
        charge: dict = {}
        if statut in params.etapes:
            charge["stage_id"] = params.etapes[statut]
        if statut == Statut.DELIVRE:
            charge["status"] = "won"
        elif statut in LOST_REASON:
            charge.update(status="lost", lost_reason=LOST_REASON[statut])
        try:
            await adapter.maj_deal(deal.id_pipedrive, charge)
        except RessourceAbsente:
            logger.warning("deal supprimé dans Pipedrive : recréation à l'étape courante (RI08)")
            deal.id_pipedrive = await self._creer_deal_pour(session, adapter, dossier, statut)
            if "status" in charge:
                await adapter.maj_deal(deal.id_pipedrive, charge)
        return deal.id_pipedrive

    async def _creer_activite(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        dossier = await session.get(Dossier, evt.dossier_id)
        deal = await self._ref_synchronisee(session, cle_deal(dossier.id))
        c = evt.charge
        repere = marqueur(dossier.reference, c["numero"])
        if ref.indetermine:
            for activite in await adapter.lister_activites_deal(deal.id_pipedrive):
                if str(activite.get("subject", "")).startswith(repere):
                    return activite["id"]
        person = await session.scalar(
            select(ReferenceSynchro).where(ReferenceSynchro.cle_idempotence == cle_person(dossier.demandeur_id))
        )
        echeance = date.fromisoformat(c["date"]) + timedelta(days=int(c["delai_jours"]))
        return await adapter.creer_activite(mappers.charge_activite(
            sujet_activite(dossier.reference, c["numero"], c["libelle"]), c["type"], echeance.isoformat(),
            deal.id_pipedrive, person.id_pipedrive if person else None, dossier.reference,
            self.settings.pipedrive_owner_id,
        ))

    async def _clore_activites(self, session, adapter, evt, ref) -> int:  # noqa: ANN001
        dossier = await session.get(Dossier, evt.dossier_id)
        deal = await self._ref_synchronisee(session, cle_deal(dossier.id))
        prefixe = f"[{dossier.reference}·"
        for activite in await adapter.lister_activites_deal(deal.id_pipedrive):
            if not activite.get("done") and str(activite.get("subject", "")).startswith(prefixe):
                try:
                    await adapter.maj_activite(activite["id"], {"done": True})
                except RessourceAbsente:
                    continue
        return deal.id_pipedrive


async def main() -> None:
    settings = get_settings()
    configurer_logging()
    worker = SyncWorker(init_engine(settings.database_url), settings)
    await worker.executer()


if __name__ == "__main__":
    asyncio.run(main())
