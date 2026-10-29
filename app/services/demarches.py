"""Types de démarches et pièces requises (FRS UC16)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflit, RegleMetierViolee, RessourceIntrouvable
from app.db.models import PieceRequise, TypeDemarche
from app.demarches.catalogue import DEMARCHES, DEMARCHES_HORS_PERIMETRE
from app.schemas.api import DemarcheModification, PieceRequiseCreation, PieceRequiseModification
from app.services import journal


async def initialiser_catalogue(session: AsyncSession) -> None:
    """Crée en base les démarches et pièces du registre absentes, sans écraser les modifications de l'admin."""
    for definition in DEMARCHES.values():
        type_ = await session.get(TypeDemarche, definition.code)
        if type_ is None:
            type_ = TypeDemarche(code=definition.code, libelle=definition.libelle,
                                 categorie=definition.categorie, actif=True)
            session.add(type_)
            for ordre, piece in enumerate(definition.pieces):
                session.add(PieceRequise(demarche_code=definition.code, code=piece.code, libelle=piece.libelle,
                                         obligatoire=piece.obligatoire, actif=True, ordre=ordre))
    await session.commit()


async def lister(session: AsyncSession) -> list[TypeDemarche]:
    return list(await session.scalars(select(TypeDemarche).order_by(TypeDemarche.categorie, TypeDemarche.code)))


async def _obtenir(session: AsyncSession, code: str) -> TypeDemarche:
    if code.upper() in DEMARCHES_HORS_PERIMETRE:
        raise RegleMetierViolee("Cette démarche est hors du périmètre de la version 1.",
                                code="DEMARCHE_HORS_PERIMETRE")
    type_ = await session.get(TypeDemarche, code)
    if type_ is None:
        raise RessourceIntrouvable()
    return type_


async def modifier(session: AsyncSession, code: str, donnees: DemarcheModification) -> TypeDemarche:
    type_ = await _obtenir(session, code)
    if donnees.libelle is not None:
        type_.libelle = donnees.libelle
    if donnees.actif is not None:
        type_.actif = donnees.actif
    journal.ecrire(session, "DEMARCHE_MODIFICATION", "SUCCES", detail=code)
    await session.commit()
    await session.refresh(type_)
    return type_


async def ajouter_piece(session: AsyncSession, code: str, donnees: PieceRequiseCreation) -> TypeDemarche:
    type_ = await _obtenir(session, code)
    if any(p.code == donnees.code for p in type_.pieces):
        raise Conflit("Cette pièce existe déjà pour la démarche.")
    session.add(PieceRequise(demarche_code=code, code=donnees.code, libelle=donnees.libelle,
                             obligatoire=donnees.obligatoire, actif=True, ordre=len(type_.pieces)))
    journal.ecrire(session, "PIECE_REQUISE_AJOUT", "SUCCES", detail=f"{code}/{donnees.code}")
    await session.commit()
    await session.refresh(type_, attribute_names=["pieces"])
    return type_


async def modifier_piece(session: AsyncSession, code: str, piece_id, donnees: PieceRequiseModification):  # noqa: ANN001
    type_ = await _obtenir(session, code)
    piece = next((p for p in type_.pieces if p.id == piece_id), None)
    if piece is None:
        raise RessourceIntrouvable()
    if donnees.libelle is not None:
        piece.libelle = donnees.libelle
    if donnees.obligatoire is not None:
        piece.obligatoire = donnees.obligatoire
    if donnees.actif is not None:
        piece.actif = donnees.actif
    journal.ecrire(session, "PIECE_REQUISE_MODIFICATION", "SUCCES", detail=f"{code}/{piece.code}")
    await session.commit()
    await session.refresh(type_, attribute_names=["pieces"])
    return type_
