"""Journal technique (RG08, FRS UC17) : sans secret ni donnée personnelle."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_correlation_id
from app.db.models import JournalTechnique
from app.integrations.pipedrive.client import AppelPipedrive


def ecrire(session: AsyncSession, operation: str, resultat: str, *, niveau: str = "INFO",
           code_erreur: str | None = None, duree_ms: int | None = None, tentative: int | None = None,
           detail: str | None = None) -> None:
    session.add(JournalTechnique(
        niveau=niveau, operation=operation, resultat=resultat, code_erreur=code_erreur,
        duree_ms=duree_ms, tentative=tentative, correlation_id=get_correlation_id(),
        detail=(detail or None) and detail[:300],
    ))


def ecrire_appels(session: AsyncSession, appels: list[AppelPipedrive], tentative: int | None = None) -> None:
    for a in appels:
        session.add(JournalTechnique(
            niveau="INFO" if a.resultat == "SUCCES" else "WARNING",
            operation=a.operation, resultat=a.resultat, code_erreur=a.code_erreur,
            duree_ms=a.duree_ms, tentative=tentative, correlation_id=a.correlation_id,
            detail=f"{a.methode} {a.route} -> {a.statut if a.statut is not None else '—'}",
        ))


async def lister(session: AsyncSession, *, niveau: str | None, operation: str | None,
                 correlation_id: str | None, du: datetime | None, au: datetime | None,
                 page: int, taille: int) -> tuple[list[JournalTechnique], int]:
    requete = select(JournalTechnique)
    if niveau:
        requete = requete.where(JournalTechnique.niveau == niveau.upper())
    if operation:
        requete = requete.where(JournalTechnique.operation == operation)
    if correlation_id:
        requete = requete.where(JournalTechnique.correlation_id == correlation_id)
    if du:
        requete = requete.where(JournalTechnique.date >= du)
    if au:
        requete = requete.where(JournalTechnique.date <= au)
    total = await session.scalar(select(func.count()).select_from(requete.subquery()))
    lignes = await session.scalars(
        requete.order_by(JournalTechnique.id.desc()).offset((page - 1) * taille).limit(taille)
    )
    return list(lignes), int(total or 0)
