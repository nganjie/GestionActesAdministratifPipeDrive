"""Initialisation idempotente du pipeline, des étapes et contrôle des types d'activités (ISD OP-05 à OP-08, OP-16)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ParametrePipedrive
from app.domain.enums import Statut
from app.domain.projection import ETAPES_PIPELINE, TYPES_ACTIVITE_REQUIS
from app.integrations.pipedrive.adapter import PipedriveAdapter
from app.integrations.pipedrive.errors import ErreurDefinitive

CLE_PIPELINE = "pipeline_id"


def cle_etape(statut: Statut) -> str:
    return f"stage:{statut}"


@dataclass
class ParametresPipeline:
    pipeline_id: int
    etapes: dict[Statut, int]


async def lire_parametres(session: AsyncSession) -> ParametresPipeline | None:
    lignes = {p.cle: p.valeur for p in await session.scalars(select(ParametrePipedrive))}
    if CLE_PIPELINE not in lignes:
        return None
    etapes = {}
    for statut, _ in ETAPES_PIPELINE:
        if cle_etape(statut) not in lignes:
            return None
        etapes[statut] = int(lignes[cle_etape(statut)])
    return ParametresPipeline(pipeline_id=int(lignes[CLE_PIPELINE]), etapes=etapes)


async def _enregistrer(session: AsyncSession, cle: str, valeur: int) -> None:
    ligne = await session.get(ParametrePipedrive, cle)
    if ligne is None:
        session.add(ParametrePipedrive(cle=cle, valeur=str(valeur)))
    else:
        ligne.valeur = str(valeur)


async def initialiser_pipeline(session: AsyncSession, adapter: PipedriveAdapter,
                               settings: Settings) -> ParametresPipeline:
    nom = settings.pipedrive_pipeline_name
    pipeline_id = next((p["id"] for p in await adapter.lister_pipelines() if p.get("name") == nom), None)
    if pipeline_id is None:
        pipeline_id = await adapter.creer_pipeline(nom)
    existantes = {e.get("name"): e["id"] for e in await adapter.lister_etapes(pipeline_id)}
    etapes: dict[Statut, int] = {}
    for statut, libelle in ETAPES_PIPELINE:
        etapes[statut] = existantes.get(libelle) or await adapter.creer_etape(libelle, pipeline_id)
    await _enregistrer(session, CLE_PIPELINE, pipeline_id)
    for statut, stage_id in etapes.items():
        await _enregistrer(session, cle_etape(statut), stage_id)
    await session.flush()
    return ParametresPipeline(pipeline_id=pipeline_id, etapes=etapes)


async def obtenir_parametres(session: AsyncSession, adapter: PipedriveAdapter,
                             settings: Settings) -> ParametresPipeline:
    return await lire_parametres(session) or await initialiser_pipeline(session, adapter, settings)


async def types_activite_manquants(adapter: PipedriveAdapter) -> list[str]:
    actifs = {t["key_string"] for t in await adapter.types_activite() if t.get("active_flag")}
    return sorted(TYPES_ACTIVITE_REQUIS - actifs)


async def verifier_types_activite(adapter: PipedriveAdapter) -> None:
    manquants = await types_activite_manquants(adapter)
    if manquants:
        raise ErreurDefinitive("TYPES_ACTIVITE_MANQUANTS",
                               "Types d'activités absents ou inactifs : " + ", ".join(manquants))
