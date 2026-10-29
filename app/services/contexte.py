"""Utilisateur authentifié courant."""

import uuid
from dataclasses import dataclass

from app.domain.enums import CATEGORIE_DU_ROLE, ROLES_INSTRUCTEURS, Categorie, Role


@dataclass(frozen=True)
class UtilisateurCourant:
    id: uuid.UUID
    nom: str
    role: Role
    categorie: Categorie | None

    @property
    def est_instructeur(self) -> bool:
        return self.role in ROLES_INSTRUCTEURS

    @property
    def categorie_effective(self) -> Categorie | None:
        return self.categorie or CATEGORIE_DU_ROLE.get(self.role)
