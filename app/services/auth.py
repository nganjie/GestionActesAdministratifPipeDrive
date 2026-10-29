"""Authentification et comptes (FRS UC01, UC02)."""

import contextlib
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import (
    AccesRefuse,
    Conflit,
    NonAuthentifie,
    RegleMetierViolee,
    RessourceIntrouvable,
    TropDeTentatives,
    ValidationEchouee,
)
from app.core.security import (
    HASH_FACTICE,
    creer_jeton_acces,
    creer_jeton_rafraichissement,
    decoder_jeton,
    hacher_mot_de_passe,
    verifier_mot_de_passe,
)
from app.db.base import maintenant
from app.db.models import JetonRevoque, Utilisateur
from app.domain.enums import CATEGORIE_DU_ROLE, Categorie, Role
from app.schemas.api import JetonsSortie, UtilisateurCreation, UtilisateurModification
from app.services import journal
from app.services.contexte import UtilisateurCourant


def _emettre(u: Utilisateur) -> JetonsSortie:
    acces, expire = creer_jeton_acces(str(u.id), u.role, u.categorie)
    rafraichissement, _ = creer_jeton_rafraichissement(str(u.id))
    return JetonsSortie(access_token=acces, refresh_token=rafraichissement, expire_le=expire, role=Role(u.role))


async def connecter(session: AsyncSession, identifiant: str, mot_de_passe: str) -> JetonsSortie:
    s = get_settings()
    u = await session.scalar(select(Utilisateur).where(Utilisateur.identifiant == identifiant))
    if u is None:
        verifier_mot_de_passe(mot_de_passe, HASH_FACTICE)
        journal.ecrire(session, "AUTH_CONNEXION", "ECHEC", niveau="WARNING", code_erreur="NON_AUTHENTIFIE")
        await session.commit()
        raise NonAuthentifie("Identifiant ou mot de passe incorrect.")
    if u.bloque_jusqua and u.bloque_jusqua > maintenant():
        raise TropDeTentatives()
    if not verifier_mot_de_passe(mot_de_passe, u.hash_mot_de_passe) or not u.actif:
        u.echecs_connexion += 1
        if u.echecs_connexion >= s.login_max_echecs:
            u.bloque_jusqua = maintenant() + timedelta(minutes=s.login_blocage_minutes)
            u.echecs_connexion = 0
        journal.ecrire(session, "AUTH_CONNEXION", "ECHEC", niveau="WARNING", code_erreur="NON_AUTHENTIFIE")
        await session.commit()
        if u.bloque_jusqua and u.bloque_jusqua > maintenant():
            raise TropDeTentatives()
        raise NonAuthentifie("Identifiant ou mot de passe incorrect.")
    u.echecs_connexion = 0
    u.bloque_jusqua = None
    journal.ecrire(session, "AUTH_CONNEXION", "SUCCES")
    await session.commit()
    return _emettre(u)


async def _est_revoque(session: AsyncSession, jti: str) -> bool:
    return await session.get(JetonRevoque, jti) is not None


async def _revoquer(session: AsyncSession, charge: dict) -> None:
    if not await _est_revoque(session, charge["jti"]):
        session.add(JetonRevoque(jti=charge["jti"], expire_le=maintenant() + timedelta(hours=9)))


async def rafraichir(session: AsyncSession, refresh_token: str) -> JetonsSortie:
    charge = decoder_jeton(refresh_token, "refresh")
    if await _est_revoque(session, charge["jti"]):
        raise NonAuthentifie("Jeton révoqué.")
    u = await session.get(Utilisateur, uuid.UUID(charge["sub"]))
    if u is None or not u.actif:
        raise NonAuthentifie()
    await _revoquer(session, charge)  # rotation : un jeton de rafraîchissement ne sert qu'une fois
    await session.commit()
    return _emettre(u)


async def deconnecter(session: AsyncSession, charge_acces: dict, refresh_token: str | None) -> None:
    await _revoquer(session, charge_acces)
    if refresh_token:
        with contextlib.suppress(NonAuthentifie):
            await _revoquer(session, decoder_jeton(refresh_token, "refresh"))
    await session.commit()


async def utilisateur_depuis_jeton(session: AsyncSession, jeton: str) -> tuple[UtilisateurCourant, dict]:
    charge = decoder_jeton(jeton, "access")
    if await _est_revoque(session, charge["jti"]):
        raise NonAuthentifie("Jeton révoqué.")
    u = await session.get(Utilisateur, uuid.UUID(charge["sub"]))
    if u is None or not u.actif:
        raise NonAuthentifie()
    categorie = Categorie(u.categorie) if u.categorie else None
    return UtilisateurCourant(id=u.id, nom=u.nom, role=Role(u.role), categorie=categorie), charge


def _verifier_categorie(role: Role, categorie: Categorie | None) -> Categorie | None:
    attendue = CATEGORIE_DU_ROLE.get(role)
    if attendue is None:
        return None
    if categorie is not None and categorie != attendue:
        raise ValidationEchouee(details=[{"champ": "categorie", "erreur": f"doit valoir {attendue}"}])
    return attendue


async def creer_utilisateur(session: AsyncSession, donnees: UtilisateurCreation) -> Utilisateur:
    if await session.scalar(select(Utilisateur.id).where(Utilisateur.identifiant == donnees.identifiant)):
        raise Conflit("Cet identifiant est déjà utilisé.")
    u = Utilisateur(
        nom=donnees.nom, identifiant=donnees.identifiant, role=donnees.role,
        categorie=_verifier_categorie(donnees.role, donnees.categorie),
        hash_mot_de_passe=hacher_mot_de_passe(donnees.mot_de_passe), actif=True,
    )
    session.add(u)
    journal.ecrire(session, "UTILISATEUR_CREATION", "SUCCES", detail=f"role={donnees.role}")
    await session.commit()
    return u


async def modifier_utilisateur(session: AsyncSession, courant: UtilisateurCourant, utilisateur_id: uuid.UUID,
                               donnees: UtilisateurModification) -> Utilisateur:
    u = await session.get(Utilisateur, utilisateur_id)
    if u is None:
        raise RessourceIntrouvable()
    if donnees.actif is False and u.id == courant.id:
        raise RegleMetierViolee("Un administrateur ne peut pas désactiver son propre compte.")
    if donnees.nom is not None:
        u.nom = donnees.nom
    if donnees.role is not None or donnees.categorie is not None:
        role = donnees.role or Role(u.role)
        u.role = role
        u.categorie = _verifier_categorie(role, donnees.categorie)
    if donnees.actif is not None:
        u.actif = donnees.actif
    if donnees.mot_de_passe:
        u.hash_mot_de_passe = hacher_mot_de_passe(donnees.mot_de_passe)
    journal.ecrire(session, "UTILISATEUR_MODIFICATION", "SUCCES")
    await session.commit()
    return u


async def lister_utilisateurs(session: AsyncSession) -> list[Utilisateur]:
    return list(await session.scalars(select(Utilisateur).order_by(Utilisateur.nom)))


async def creer_admin_initial(session: AsyncSession, settings: Settings) -> None:
    if not settings.admin_identifiant or not settings.admin_mot_de_passe:
        return
    existe = await session.scalar(select(Utilisateur.id).where(Utilisateur.role == Role.ADMIN).limit(1))
    if existe:
        return
    session.add(Utilisateur(
        nom=settings.admin_nom, identifiant=settings.admin_identifiant, role=Role.ADMIN, categorie=None,
        hash_mot_de_passe=hacher_mot_de_passe(settings.admin_mot_de_passe.get_secret_value()), actif=True,
    ))
    await session.commit()


def exiger_role(courant: UtilisateurCourant, *roles: Role) -> None:
    if courant.role not in roles:
        raise AccesRefuse()
