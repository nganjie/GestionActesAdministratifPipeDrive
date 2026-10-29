"""Types validés partagés (FRS §6.3)."""

import re
import unicodedata
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

_NOM_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' \-]*[A-Za-zÀ-ÖØ-öø-ÿ]$")
_TEL_RE = re.compile(r"^\+237\d{9}$")


def _valider_nom(v: str) -> str:
    v = " ".join(v.split())
    if not 2 <= len(v) <= 80 or not _NOM_RE.match(v):
        raise ValueError("2 à 80 caractères : lettres, espaces, tirets et apostrophes uniquement")
    return v


def _normaliser_telephone(v: str) -> str:
    brut = re.sub(r"[\s.\-()]", "", v)
    if brut.startswith("00237"):
        brut = "+" + brut[2:]
    elif re.fullmatch(r"\d{9}", brut):
        brut = "+237" + brut
    if not _TEL_RE.match(brut):
        raise ValueError("format attendu : +237 suivi de 9 chiffres")
    return brut


def _non_future(v: date) -> date:
    if v > date.today():
        raise ValueError("la date ne peut pas être dans le futur")
    return v


def _future_ou_jour(v: date) -> date:
    if v < date.today():
        raise ValueError("la date doit être aujourd'hui ou dans le futur")
    return v


Nom = Annotated[str, AfterValidator(_valider_nom)]
Telephone = Annotated[str, AfterValidator(_normaliser_telephone)]
DatePassee = Annotated[date, AfterValidator(_non_future)]
DateFuture = Annotated[date, AfterValidator(_future_ou_jour)]
Motif = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]
TexteCourt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def normaliser_cle(*parties: object) -> str:
    """Normalise des valeurs pour une clé de doublon : minuscules, sans accents ni espaces superflus."""
    morceaux = []
    for p in parties:
        s = unicodedata.normalize("NFKD", str(p)).encode("ascii", "ignore").decode().lower()
        morceaux.append(" ".join(s.split()))
    return "|".join(morceaux)
