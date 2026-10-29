"""Modèle de données (AF §10, FRS §6.1)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, maintenant


class Utilisateur(Base):
    __tablename__ = "utilisateurs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(120))
    identifiant: Mapped[str] = mapped_column(String(80), unique=True)
    hash_mot_de_passe: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30))
    categorie: Mapped[str | None] = mapped_column(String(30))
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    echecs_connexion: Mapped[int] = mapped_column(Integer, default=0)
    bloque_jusqua: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)


class JetonRevoque(Base):
    __tablename__ = "jetons_revoques"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expire_le: Mapped[datetime] = mapped_column(UTCDateTime())


class Demandeur(Base):
    __tablename__ = "demandeurs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(80))
    prenom: Mapped[str] = mapped_column(String(80))
    telephone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    date_naissance: Mapped[date | None] = mapped_column(Date)
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    maj_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant, onupdate=maintenant)


class TypeDemarche(Base):
    __tablename__ = "types_demarche"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    libelle: Mapped[str] = mapped_column(String(120))
    categorie: Mapped[str] = mapped_column(String(30))
    actif: Mapped[bool] = mapped_column(Boolean, default=True)

    pieces: Mapped[list["PieceRequise"]] = relationship(
        back_populates="demarche", order_by="PieceRequise.ordre", lazy="selectin"
    )


class PieceRequise(Base):
    __tablename__ = "pieces_requises"
    __table_args__ = (UniqueConstraint("demarche_code", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    demarche_code: Mapped[str] = mapped_column(ForeignKey("types_demarche.code"))
    code: Mapped[str] = mapped_column(String(60))
    libelle: Mapped[str] = mapped_column(String(160))
    obligatoire: Mapped[bool] = mapped_column(Boolean, default=True)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    demarche: Mapped[TypeDemarche] = relationship(back_populates="pieces")


class Compteur(Base):
    __tablename__ = "compteurs"

    cle: Mapped[str] = mapped_column(String(40), primary_key=True)
    valeur: Mapped[int] = mapped_column(Integer, default=0)


class Dossier(Base):
    __tablename__ = "dossiers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(20), unique=True)
    type_demarche: Mapped[str] = mapped_column(ForeignKey("types_demarche.code"))
    categorie: Mapped[str] = mapped_column(String(30), index=True)
    objet: Mapped[str] = mapped_column(String(200))
    donnees_specifiques: Mapped[dict[str, Any]] = mapped_column(JSON)
    cle_doublon: Mapped[str] = mapped_column(String(400), index=True)
    statut: Mapped[str] = mapped_column(String(30), index=True)
    demandeur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("demandeurs.id"), index=True)
    createur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    instructeur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    maj_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant, onupdate=maintenant)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}

    demandeur: Mapped[Demandeur] = relationship(lazy="joined")
    demarche: Mapped[TypeDemarche] = relationship(lazy="joined")
    pieces_requises: Mapped[list["DossierPieceRequise"]] = relationship(
        order_by="DossierPieceRequise.ordre", lazy="selectin", cascade="all, delete-orphan"
    )
    pieces_fournies: Mapped[list["PieceFournie"]] = relationship(
        order_by="PieceFournie.cree_le", lazy="selectin", cascade="all, delete-orphan"
    )
    decision: Mapped["Decision | None"] = relationship(lazy="selectin", uselist=False)


class DossierPieceRequise(Base):
    """Copie des pièces requises au moment de la création (FRS UC16 : les dossiers existants les conservent)."""

    __tablename__ = "dossier_pieces_requises"
    __table_args__ = (UniqueConstraint("dossier_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossiers.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    libelle: Mapped[str] = mapped_column(String(160))
    obligatoire: Mapped[bool] = mapped_column(Boolean)
    ordre: Mapped[int] = mapped_column(Integer, default=0)


class PieceFournie(Base):
    __tablename__ = "pieces_fournies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossiers.id"), index=True)
    code_piece: Mapped[str] = mapped_column(String(60))
    date_reception: Mapped[date] = mapped_column(Date)
    etat: Mapped[str] = mapped_column(String(20))
    observation: Mapped[str | None] = mapped_column(String(500))
    declaree_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    maj_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant, onupdate=maintenant)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossiers.id"), unique=True)
    issue: Mapped[str] = mapped_column(String(20))
    motif: Mapped[str | None] = mapped_column(String(500))
    auteur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    date: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)


class EvenementHistorique(Base):
    """Historique en ajout seul (RM07) : aucune API ne modifie ni ne supprime ces lignes."""

    __tablename__ = "evenements_historique"
    __table_args__ = (UniqueConstraint("dossier_id", "numero"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossiers.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40))
    ancien_statut: Mapped[str | None] = mapped_column(String(30))
    nouveau_statut: Mapped[str | None] = mapped_column(String(30))
    auteur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    date: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    commentaire: Mapped[str | None] = mapped_column(Text)


class ReferenceSynchro(Base):
    """Correspondance interne ↔ Pipedrive et état de synchronisation (RG04, FRS RI03-RI04)."""

    __tablename__ = "references_synchro"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cle_idempotence: Mapped[str] = mapped_column(String(200), unique=True)
    objet_type: Mapped[str] = mapped_column(String(30))
    objet_id: Mapped[str] = mapped_column(String(64), index=True)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dossiers.id"), index=True)
    type_pipedrive: Mapped[str] = mapped_column(String(20))
    id_pipedrive: Mapped[int | None] = mapped_column(Integer)
    etat: Mapped[str] = mapped_column(String(20), index=True)
    tentatives: Mapped[int] = mapped_column(Integer, default=0)
    prochaine_tentative: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    indetermine: Mapped[bool] = mapped_column(Boolean, default=False)
    code_erreur: Mapped[str | None] = mapped_column(String(60))
    derniere_erreur: Mapped[str | None] = mapped_column(String(300))
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)
    maj_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant, onupdate=maintenant)


class EvenementOutbox(Base):
    """File d'événements écrite dans la transaction métier (FRS RI02)."""

    __tablename__ = "evenements_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(40))
    reference_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("references_synchro.id"), unique=True)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dossiers.id"), index=True)
    demandeur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("demandeurs.id"))
    charge: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    traite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    cree_le: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant)

    reference: Mapped[ReferenceSynchro] = relationship(lazy="joined", innerjoin=True)


class JournalTechnique(Base):
    __tablename__ = "journal_technique"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(UTCDateTime(), default=maintenant, index=True)
    niveau: Mapped[str] = mapped_column(String(10))
    operation: Mapped[str] = mapped_column(String(60), index=True)
    resultat: Mapped[str] = mapped_column(String(30))
    code_erreur: Mapped[str | None] = mapped_column(String(60))
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    tentative: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(String(300))


class ParametrePipedrive(Base):
    """Identifiants Pipedrive initialisés (pipeline, étapes) — ISD §5.4."""

    __tablename__ = "parametres_pipedrive"

    cle: Mapped[str] = mapped_column(String(60), primary_key=True)
    valeur: Mapped[str] = mapped_column(String(120))
