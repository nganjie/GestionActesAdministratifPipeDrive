"""Dépendances FastAPI : session, utilisateur courant, contrôle des rôles, adaptateur Pipedrive."""

from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AccesRefuse, NonAuthentifie
from app.db.base import get_session_factory
from app.domain.enums import Role
from app.integrations.pipedrive.adapter import PipedriveAdapter
from app.integrations.pipedrive.client import AppelPipedrive, PipedriveClient
from app.services import auth
from app.services.contexte import UtilisateurCourant

_bearer = HTTPBearer(auto_error=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


async def get_utilisateur(
    request: Request, session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UtilisateurCourant:
    if credentials is None:
        raise NonAuthentifie()
    courant, charge = await auth.utilisateur_depuis_jeton(session, credentials.credentials)
    request.state.charge_jeton = charge
    return courant


Courant = Annotated[UtilisateurCourant, Depends(get_utilisateur)]


def exiger_roles(*roles: Role) -> Callable[[UtilisateurCourant], UtilisateurCourant]:
    def _verifier(courant: Courant) -> UtilisateurCourant:
        if courant.role not in roles:
            raise AccesRefuse()
        return courant
    return _verifier


Admin = Annotated[UtilisateurCourant, Depends(exiger_roles(Role.ADMIN))]


class AdapterLecture:
    """Adaptateur pour les lectures synchrones (OP-01, OP-13, OP-16) ; collecte les appels pour le journal."""

    def __init__(self) -> None:
        self.appels: list[AppelPipedrive] = []
        self.adapter = PipedriveAdapter(PipedriveClient(get_settings(), on_appel=self.appels.append))


async def get_adapter_lecture() -> AsyncIterator[AdapterLecture]:
    lecture = AdapterLecture()
    try:
        yield lecture
    finally:
        await lecture.adapter.client.aclose()


Lecture = Annotated[AdapterLecture, Depends(get_adapter_lecture)]
