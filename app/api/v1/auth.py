"""Authentification (FRS UC01) et comptes (UC02)."""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import Admin, Courant, Session
from app.db.models import Utilisateur
from app.schemas.api import (
    ConnexionEntree,
    JetonsSortie,
    RafraichissementEntree,
    UtilisateurCreation,
    UtilisateurModification,
    UtilisateurSortie,
)
from app.services import auth

router = APIRouter(tags=["Authentification et comptes"])


@router.post("/auth/login", response_model=JetonsSortie, summary="S'authentifier (UC01)")
async def login(donnees: ConnexionEntree, session: Session) -> JetonsSortie:
    return await auth.connecter(session, donnees.identifiant, donnees.mot_de_passe)


@router.post("/auth/refresh", response_model=JetonsSortie, summary="Renouveler les jetons")
async def refresh(donnees: RafraichissementEntree, session: Session) -> JetonsSortie:
    return await auth.rafraichir(session, donnees.refresh_token)


@router.get("/auth/me", response_model=UtilisateurSortie, summary="Utilisateur connecté")
async def me(courant: Courant, session: Session) -> UtilisateurSortie:
    return UtilisateurSortie.model_validate(await session.get(Utilisateur, courant.id))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Se déconnecter")
async def logout(request: Request, courant: Courant, session: Session,
                 donnees: RafraichissementEntree | None = None) -> None:
    await auth.deconnecter(session, request.state.charge_jeton, donnees.refresh_token if donnees else None)


@router.get("/utilisateurs", response_model=list[UtilisateurSortie], summary="Lister les comptes (UC02)")
async def lister_utilisateurs(_: Admin, session: Session) -> list[UtilisateurSortie]:
    return [UtilisateurSortie.model_validate(u) for u in await auth.lister_utilisateurs(session)]


@router.post("/utilisateurs", response_model=UtilisateurSortie, status_code=status.HTTP_201_CREATED,
             summary="Créer un compte (UC02)")
async def creer_utilisateur(donnees: UtilisateurCreation, _: Admin, session: Session) -> UtilisateurSortie:
    return UtilisateurSortie.model_validate(await auth.creer_utilisateur(session, donnees))


@router.patch("/utilisateurs/{utilisateur_id}", response_model=UtilisateurSortie, summary="Modifier un compte")
async def modifier_utilisateur(utilisateur_id: uuid.UUID, donnees: UtilisateurModification, courant: Admin,
                               session: Session) -> UtilisateurSortie:
    return UtilisateurSortie.model_validate(
        await auth.modifier_utilisateur(session, courant, utilisateur_id, donnees)
    )
