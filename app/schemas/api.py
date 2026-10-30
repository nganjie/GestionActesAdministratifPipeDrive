"""Schémas d'entrée et de sortie de l'API exposée (FRS §5, §7)."""

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.enums import Categorie, EtatPiece, EtatSynchro, IssueDecision, Role, Statut
from app.schemas.types import DatePassee, Motif, Nom, Telephone, TexteCourt

T = TypeVar("T")


class Entree(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Sortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    elements: list[T]
    total: int
    page: int
    taille: int


# --- Authentification ----------------------------------------------------------------------------

class ConnexionEntree(Entree):
    identifiant: str = Field(min_length=1, max_length=80)
    mot_de_passe: str = Field(min_length=1, max_length=200)


class RafraichissementEntree(Entree):
    refresh_token: str


class JetonsSortie(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expire_le: datetime
    role: Role


class UtilisateurSortie(Sortie):
    id: uuid.UUID
    nom: str
    identifiant: str
    role: Role
    categorie: Categorie | None
    actif: bool


class UtilisateurCreation(Entree):
    nom: TexteCourt
    identifiant: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    mot_de_passe: str = Field(min_length=12, max_length=200)
    role: Role
    categorie: Categorie | None = None


class UtilisateurModification(Entree):
    nom: TexteCourt | None = None
    role: Role | None = None
    categorie: Categorie | None = None
    actif: bool | None = None
    mot_de_passe: str | None = Field(default=None, min_length=12, max_length=200)


# --- Démarches ----------------------------------------------------------------------------------

class PieceRequiseSortie(Sortie):
    id: uuid.UUID
    code: str
    libelle: str
    obligatoire: bool
    actif: bool


class DemarcheSortie(Sortie):
    code: str
    libelle: str
    categorie: Categorie
    actif: bool
    pieces: list[PieceRequiseSortie]


class DemarcheModification(Entree):
    libelle: TexteCourt | None = None
    actif: bool | None = None


class PieceRequiseCreation(Entree):
    code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Z0-9_]+$")
    libelle: TexteCourt
    obligatoire: bool = True


class PieceRequiseModification(Entree):
    libelle: TexteCourt | None = None
    obligatoire: bool | None = None
    actif: bool | None = None


# --- Dossiers -----------------------------------------------------------------------------------

class DemandeurEntree(Entree):
    nom: Nom
    prenom: Nom
    telephone: Telephone | None = None
    email: EmailStr | None = None
    date_naissance: DatePassee | None = None

    @model_validator(mode="after")
    def _un_contact(self) -> "DemandeurEntree":
        if not self.telephone and not self.email:
            raise ValueError("le téléphone ou l'e-mail est obligatoire")
        return self


class DossierCreation(Entree):
    type_demarche: str = Field(min_length=2, max_length=40)
    demandeur: DemandeurEntree
    objet: TexteCourt
    donnees_specifiques: dict[str, Any]
    confirmer_doublon: bool = False
    motif_doublon: Motif | None = None


class DossierModification(Entree):
    demandeur: DemandeurEntree | None = None
    objet: TexteCourt | None = None
    donnees_specifiques: dict[str, Any] | None = None
    type_demarche: str | None = None  # refusé : il faut annuler et recréer (FRS UC06)


class DemandeurSortie(Sortie):
    id: uuid.UUID
    nom: str
    prenom: str
    telephone: str | None
    email: str | None
    date_naissance: date | None


class PieceRequiseDossierSortie(Sortie):
    code: str
    libelle: str
    obligatoire: bool


class PieceFournieSortie(Sortie):
    id: uuid.UUID
    code_piece: str
    date_reception: date
    etat: EtatPiece
    observation: str | None
    cree_le: datetime
    maj_le: datetime


class DecisionSortie(Sortie):
    issue: IssueDecision
    motif: str | None
    auteur_id: uuid.UUID
    auteur_nom: str | None = None
    date: datetime


class ObjetSynchroSortie(BaseModel):
    id: uuid.UUID
    type: str
    objet: str
    etat: EtatSynchro
    id_pipedrive: int | None
    tentatives: int
    code_erreur: str | None
    derniere_erreur: str | None
    prochaine_tentative: datetime | None


class SynchronisationSortie(BaseModel):
    etat: EtatSynchro | None
    objets: list[ObjetSynchroSortie]


class DossierResume(BaseModel):
    id: uuid.UUID
    reference: str
    type_demarche: str
    libelle_demarche: str
    categorie: Categorie
    statut: Statut
    demandeur: str
    instructeur_id: uuid.UUID | None
    synchronisation: EtatSynchro | None
    maj_le: datetime


class DossierSortie(BaseModel):
    id: uuid.UUID
    reference: str
    type_demarche: str
    libelle_demarche: str
    categorie: Categorie
    statut: Statut
    objet: str
    donnees_specifiques: dict[str, Any]
    demandeur: DemandeurSortie
    createur_id: uuid.UUID
    createur_nom: str | None = None
    instructeur_id: uuid.UUID | None
    instructeur_nom: str | None = None
    pieces_requises: list[PieceRequiseDossierSortie]
    pieces_fournies: list[PieceFournieSortie]
    decision: DecisionSortie | None
    synchronisation: SynchronisationSortie
    version: int
    cree_le: datetime
    maj_le: datetime


class PieceDeclaration(Entree):
    code_piece: str = Field(min_length=2, max_length=60)
    date_reception: DatePassee
    etat: Literal[EtatPiece.CONFORME, EtatPiece.A_CORRIGER]
    observation: str | None = Field(default=None, max_length=500)


class PieceMiseAJour(Entree):
    date_reception: DatePassee | None = None
    etat: EtatPiece | None = None
    observation: str | None = Field(default=None, max_length=500)


class VerificationSortie(BaseModel):
    complet: bool
    pieces_manquantes: list[PieceRequiseDossierSortie]
    statut: Statut
    transition_proposee: Statut | None


class TransitionEntree(Entree):
    statut_cible: Statut
    motif: Motif | None = None
    commentaire: str | None = Field(default=None, max_length=500)


class DecisionEntree(Entree):
    issue: IssueDecision
    motif: Motif | None = None


class AnnulationEntree(Entree):
    motif: Motif | None = None


class EvenementHistoriqueSortie(Sortie):
    numero: int
    type: str
    ancien_statut: Statut | None
    nouveau_statut: Statut | None
    auteur_id: uuid.UUID | None
    auteur_nom: str | None = None
    date: datetime
    commentaire: str | None


class ActiviteSortie(BaseModel):
    id_externe: int
    intitule: str
    type: str | None
    echeance: str | None
    terminee: bool


class ActivitesSortie(BaseModel):
    disponible: bool
    raison: str | None = None
    elements: list[ActiviteSortie] = []


# --- Synchronisations, journaux, santé -------------------------------------------------------------

class ReferenceSynchroSortie(Sortie):
    id: uuid.UUID
    cle_idempotence: str
    objet_type: str
    objet_id: str
    dossier_id: uuid.UUID | None
    type_pipedrive: str
    id_pipedrive: int | None
    etat: EtatSynchro
    tentatives: int
    prochaine_tentative: datetime
    indetermine: bool
    code_erreur: str | None
    derniere_erreur: str | None
    maj_le: datetime


class JournalSortie(Sortie):
    id: int
    date: datetime
    niveau: str
    operation: str
    resultat: str
    code_erreur: str | None
    duree_ms: int | None
    tentative: int | None
    correlation_id: str | None
    detail: str | None


class SantePipedriveSortie(BaseModel):
    configure: bool
    jeton_valide: bool | None
    compte_id: int | None = None
    company_domain: str | None = None
    pipeline_initialise: bool
    types_activite_manquants: list[str] = []
    synchronisations: dict[str, int]
    erreur: str | None = None


class DemoEtatSortie(BaseModel):
    actif: bool
    pipedrive: bool
    pipeline: str


class DemoReinitialisation(Entree):
    confirmation: str = Field(max_length=40)


class DemoBilanSortie(BaseModel):
    dossiers_supprimes: int
    deals_supprimes: int
    activites_supprimees: int
    dossiers_crees: int
    pipedrive: bool
