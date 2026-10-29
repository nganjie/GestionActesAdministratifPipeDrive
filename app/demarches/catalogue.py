"""Les cinq démarches de la version 1 (CDC §2.2, FRS §6.2).

Les pièces sont des hypothèses de travail (AF H4) : elles sont copiées en base au démarrage
puis modifiables par l'administrateur (UC16).
"""

from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.demarches.base import DefinitionDemarche, DonneesSpecifiques, PieceParDefaut
from app.domain.enums import Categorie
from app.schemas.types import DateFuture, DatePassee, Nom, TexteCourt, normaliser_cle


class Personne(DonneesSpecifiques):
    nom: Nom
    prenom: Nom
    date_naissance: DatePassee | None = None


class Temoin(DonneesSpecifiques):
    nom: Nom
    prenom: Nom


# --- Acte de mariage -------------------------------------------------------------------------

class DonneesMariage(DonneesSpecifiques):
    epoux_1: Personne
    epoux_2: Personne
    date_celebration_prevue: DateFuture
    temoins: list[Temoin] = Field(min_length=2, max_length=4)


def _cle_mariage(d: DonneesMariage, _demandeur_id: str) -> str:
    epoux = sorted(
        normaliser_cle(e.nom, e.prenom, e.date_naissance or "") for e in (d.epoux_1, d.epoux_2)
    )
    return "MARIAGE:" + "+".join(epoux)


# --- Acte de décès ---------------------------------------------------------------------------

class DonneesDeces(DonneesSpecifiques):
    defunt: Personne
    date_deces: DatePassee
    lieu_deces: TexteCourt
    lien_declarant: TexteCourt

    @model_validator(mode="after")
    def _coherence_dates(self) -> "DonneesDeces":
        if self.defunt.date_naissance and self.defunt.date_naissance > self.date_deces:
            raise ValueError("la date de décès précède la date de naissance")
        return self


def _cle_deces(d: DonneesDeces, _demandeur_id: str) -> str:
    return "DECES:" + normaliser_cle(d.defunt.nom, d.defunt.prenom, d.date_deces)


# --- Copie d'acte ------------------------------------------------------------------------------

class DonneesCopieActe(DonneesSpecifiques):
    # NAISSANCE est accepté par le schéma pour être refusé explicitement par RM08 (422).
    type_acte: Literal["MARIAGE", "DECES", "NAISSANCE"]
    numero_acte: TexteCourt
    annee: int = Field(ge=1900)
    centre_etat_civil: TexteCourt
    nombre_copies: int = Field(default=1, ge=1, le=10)
    qualite_demandeur: TexteCourt

    @field_validator("annee")
    @classmethod
    def _annee_passee(cls, v: int) -> int:
        if v > date.today().year:
            raise ValueError("l'année ne peut pas être dans le futur")
        return v


def _cle_copie(d: DonneesCopieActe, demandeur_id: str) -> str:
    return "COPIE:" + normaliser_cle(d.type_acte, d.numero_acte, d.annee, d.centre_etat_civil, demandeur_id)


# --- Légalisation de signature ----------------------------------------------------------------

class DonneesLegalisation(DonneesSpecifiques):
    intitule_document: TexteCourt
    signataire: Personne
    qualite_signataire: TexteCourt
    nombre_exemplaires: int = Field(default=1, ge=1, le=20)


def _cle_legalisation(d: DonneesLegalisation, demandeur_id: str) -> str:
    return "LEGALISATION:" + normaliser_cle(
        demandeur_id, d.signataire.nom, d.signataire.prenom, d.intitule_document
    )


# --- Certification conforme -------------------------------------------------------------------

class DonneesCertification(DonneesSpecifiques):
    intitule_document: TexteCourt
    nombre_copies: int = Field(default=1, ge=1, le=20)


def _cle_certification(d: DonneesCertification, demandeur_id: str) -> str:
    return "CERTIFICATION:" + normaliser_cle(demandeur_id, d.intitule_document)


DEMARCHES: dict[str, DefinitionDemarche] = {
    d.code: d
    for d in (
        DefinitionDemarche(
            code="MARIAGE", libelle="Acte de mariage", categorie=Categorie.ETAT_CIVIL,
            schema=DonneesMariage, cle_doublon=_cle_mariage,
            pieces=(
                PieceParDefaut("IDENTITE_EPOUX", "Pièces d'identité des époux"),
                PieceParDefaut("EXTRAITS_NAISSANCE", "Extraits d'acte de naissance des époux"),
                PieceParDefaut("JUSTIFICATIFS_RESIDENCE", "Justificatifs de résidence"),
                PieceParDefaut("IDENTITE_TEMOINS", "Pièces d'identité des témoins"),
            ),
        ),
        DefinitionDemarche(
            code="DECES", libelle="Acte de décès", categorie=Categorie.ETAT_CIVIL,
            schema=DonneesDeces, cle_doublon=_cle_deces,
            pieces=(
                PieceParDefaut("CERTIFICAT_DECES", "Certificat de décès"),
                PieceParDefaut("IDENTITE_DEFUNT", "Pièce d'identité du défunt"),
                PieceParDefaut("IDENTITE_DECLARANT", "Pièce d'identité du déclarant"),
            ),
        ),
        DefinitionDemarche(
            code="COPIE_ACTE", libelle="Copie d'acte d'état civil", categorie=Categorie.ETAT_CIVIL,
            schema=DonneesCopieActe, cle_doublon=_cle_copie,
            pieces=(
                PieceParDefaut("IDENTITE_DEMANDEUR", "Pièce d'identité du demandeur"),
                PieceParDefaut("JUSTIFICATIF_QUALITE", "Justificatif de qualité", obligatoire=False),
            ),
        ),
        DefinitionDemarche(
            code="LEGALISATION", libelle="Légalisation de signature", categorie=Categorie.CERTIFICATION,
            schema=DonneesLegalisation, cle_doublon=_cle_legalisation,
            pieces=(
                PieceParDefaut("DOCUMENT_SIGNE", "Document signé"),
                PieceParDefaut("IDENTITE_SIGNATAIRE", "Pièce d'identité du signataire"),
            ),
        ),
        DefinitionDemarche(
            code="CERTIFICATION_CONFORME", libelle="Certification conforme de copies",
            categorie=Categorie.CERTIFICATION, schema=DonneesCertification, cle_doublon=_cle_certification,
            pieces=(
                PieceParDefaut("ORIGINAL", "Original présenté"),
                PieceParDefaut("COPIES", "Copies à certifier"),
                PieceParDefaut("IDENTITE_DEMANDEUR", "Pièce d'identité du demandeur"),
            ),
        ),
    )
}

# Codes refusés explicitement (RM08).
DEMARCHES_HORS_PERIMETRE = frozenset({"NAISSANCE", "COPIE_ACTE_NAISSANCE"})
