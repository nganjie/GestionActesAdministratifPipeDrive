"""Définition d'une démarche administrative (FRS §6.2, EF17).

Ajouter une démarche = ajouter un module au registre ; l'adaptateur Pipedrive n'est pas touché (RG09).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import Categorie


class DonneesSpecifiques(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class PieceParDefaut:
    code: str
    libelle: str
    obligatoire: bool = True


@dataclass(frozen=True)
class DefinitionDemarche:
    code: str
    libelle: str
    categorie: Categorie
    schema: type[DonneesSpecifiques]
    pieces: tuple[PieceParDefaut, ...]
    # (données validées, identifiant du demandeur) -> clé de doublon (RM02)
    cle_doublon: Callable[[Any, str], str]

    def valider(self, donnees: dict[str, Any]) -> DonneesSpecifiques:
        return self.schema.model_validate(donnees)
