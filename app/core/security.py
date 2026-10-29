"""Hachage des mots de passe (argon2) et jetons JWT (FRS UC01)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.errors import JetonExpire, NonAuthentifie

_hasher = PasswordHash.recommended()
ALGORITHME = "HS256"


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    return _hasher.hash(mot_de_passe)


def verifier_mot_de_passe(mot_de_passe: str, hash_: str) -> bool:
    try:
        return _hasher.verify(mot_de_passe, hash_)
    except Exception:
        return False


# Hash factice pour garder un temps de réponse constant quand l'identifiant n'existe pas.
HASH_FACTICE = hacher_mot_de_passe("mot-de-passe-factice-pour-temps-constant")


def _creer_jeton(sujet: str, type_jeton: str, duree: timedelta, claims: dict[str, Any]) -> tuple[str, datetime]:
    maintenant = datetime.now(UTC)
    expire = maintenant + duree
    charge = {
        "sub": sujet,
        "type": type_jeton,
        "jti": str(uuid.uuid4()),
        "iat": maintenant,
        "exp": expire,
        **claims,
    }
    jeton = jwt.encode(charge, get_settings().jwt_secret.get_secret_value(), algorithm=ALGORITHME)
    return jeton, expire


def creer_jeton_acces(utilisateur_id: str, role: str, categorie: str | None) -> tuple[str, datetime]:
    duree = timedelta(minutes=get_settings().jwt_access_minutes)
    return _creer_jeton(utilisateur_id, "access", duree, {"role": role, "categorie": categorie})


def creer_jeton_rafraichissement(utilisateur_id: str) -> tuple[str, datetime]:
    return _creer_jeton(utilisateur_id, "refresh", timedelta(hours=get_settings().jwt_refresh_hours), {})


def decoder_jeton(jeton: str, type_attendu: str) -> dict[str, Any]:
    try:
        charge = jwt.decode(jeton, get_settings().jwt_secret.get_secret_value(), algorithms=[ALGORITHME])
    except jwt.ExpiredSignatureError as exc:
        raise JetonExpire() from exc
    except jwt.PyJWTError as exc:
        raise NonAuthentifie("Jeton invalide.") from exc
    if charge.get("type") != type_attendu:
        raise NonAuthentifie("Type de jeton invalide.")
    return charge
