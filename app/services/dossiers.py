"""Gestion des dossiers : création, consultation, pièces, cycle de vie, décision (FRS UC03 à UC12)."""

import uuid
from datetime import UTC, date, datetime, time

from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AccesRefuse,
    Conflit,
    RegleMetierViolee,
    RessourceIntrouvable,
    ValidationEchouee,
)
from app.db.models import (
    Compteur,
    Decision,
    Demandeur,
    Dossier,
    DossierPieceRequise,
    EvenementHistorique,
    PieceFournie,
    ReferenceSynchro,
    TypeDemarche,
)
from app.demarches.catalogue import DEMARCHES, DEMARCHES_HORS_PERIMETRE
from app.domain.cycle_de_vie import STATUTS_PAR_DECISION, peut_acceder, trouver_transition
from app.domain.enums import (
    STATUTS_ANNULABLES,
    STATUTS_TERMINAUX,
    Categorie,
    EtatPiece,
    EtatSynchro,
    IssueDecision,
    Role,
    Statut,
)
from app.schemas.api import (
    DemandeurEntree,
    DossierCreation,
    DossierModification,
    PieceDeclaration,
    PieceMiseAJour,
    PieceRequiseDossierSortie,
    VerificationSortie,
)
from app.services import synchronisation as sync
from app.services.contexte import UtilisateurCourant

STATUTS_DECLARATION_PIECES = frozenset({Statut.BROUILLON, Statut.SOUMIS, Statut.INCOMPLET})


# --- Outils internes --------------------------------------------------------------------------------

def _details_validation(exc: ValidationError, prefixe: str) -> list[dict[str, str]]:
    return [
        {"champ": ".".join([prefixe, *(str(p) for p in e["loc"])]).strip("."),
         "erreur": e["msg"].removeprefix("Value error, ")}
        for e in exc.errors()
    ]


def _exiger(courant: UtilisateurCourant, *roles: Role) -> None:
    if courant.role not in roles:
        raise AccesRefuse()


async def _prochaine_reference(session: AsyncSession) -> str:
    annee = date.today().year
    cle = f"ACT-{annee}"
    for _ in range(3):
        valeur = await session.scalar(
            update(Compteur).where(Compteur.cle == cle).values(valeur=Compteur.valeur + 1)
            .returning(Compteur.valeur)
        )
        if valeur is not None:
            return f"ACT-{annee}-{valeur:06d}"
        try:
            async with session.begin_nested():
                session.add(Compteur(cle=cle, valeur=1))
            return f"ACT-{annee}-{1:06d}"
        except IntegrityError:
            continue
    raise RuntimeError("Impossible d'attribuer une référence de dossier")


async def _ajouter_historique(session: AsyncSession, dossier: Dossier, type_: str, courant: UtilisateurCourant,
                              *, ancien: Statut | None = None, nouveau: Statut | None = None,
                              commentaire: str | None = None) -> int:
    dernier = await session.scalar(
        select(func.max(EvenementHistorique.numero)).where(EvenementHistorique.dossier_id == dossier.id)
    )
    numero = int(dernier or 0) + 1
    session.add(EvenementHistorique(
        dossier_id=dossier.id, numero=numero, type=type_, ancien_statut=ancien, nouveau_statut=nouveau,
        auteur_id=courant.id, commentaire=commentaire,
    ))
    await session.flush()
    return numero


async def _resoudre_demandeur(session: AsyncSession, donnees: DemandeurEntree) -> Demandeur:
    """Réutilise le demandeur connu par e-mail ou téléphone (UC03-A1), sinon le crée."""
    email = donnees.email.lower() if donnees.email else None
    conditions = []
    if email:
        conditions.append(func.lower(Demandeur.email) == email)
    if donnees.telephone:
        conditions.append(Demandeur.telephone == donnees.telephone)
    existant = await session.scalar(select(Demandeur).where(or_(*conditions)).order_by(Demandeur.cree_le).limit(1))
    if existant is None:
        demandeur = Demandeur(nom=donnees.nom.upper(), prenom=donnees.prenom, telephone=donnees.telephone,
                              email=email, date_naissance=donnees.date_naissance)
        session.add(demandeur)
        await session.flush()
        await sync.enfiler_demandeur(session, demandeur)
        return demandeur
    modifie = False
    for champ, valeur in (("nom", donnees.nom.upper()), ("prenom", donnees.prenom),
                          ("telephone", donnees.telephone), ("email", email),
                          ("date_naissance", donnees.date_naissance)):
        if valeur and getattr(existant, champ) != valeur:
            setattr(existant, champ, valeur)
            modifie = modifie or champ in ("nom", "prenom", "telephone", "email")
    await session.flush()
    person = await session.scalar(
        select(ReferenceSynchro).where(ReferenceSynchro.cle_idempotence == sync.cle_person(existant.id))
    )
    if person is None:
        await sync.enfiler_demandeur(session, existant)
    elif modifie and person.etat == EtatSynchro.SYNCHRONISE:
        await sync.enfiler_maj_demandeur(session, existant)
    return existant


async def _type_actif(session: AsyncSession, code: str) -> TypeDemarche:
    if code.upper() in DEMARCHES_HORS_PERIMETRE:
        raise RegleMetierViolee("L'acte de naissance est hors du périmètre de la version 1.",
                                code="DEMARCHE_HORS_PERIMETRE")
    type_ = await session.get(TypeDemarche, code)
    if type_ is None or not type_.actif or code not in DEMARCHES:
        raise RegleMetierViolee("Type de démarche inconnu ou inactif.", code="DEMARCHE_INACTIVE")
    return type_


def _valider_donnees(code: str, donnees: dict, demandeur_id: uuid.UUID) -> tuple[dict, str]:
    definition = DEMARCHES[code]
    try:
        valide = definition.valider(donnees)
    except ValidationError as exc:
        raise ValidationEchouee(details=_details_validation(exc, "donnees_specifiques")) from exc
    if getattr(valide, "type_acte", None) == "NAISSANCE":
        raise RegleMetierViolee("La copie d'acte de naissance est hors du périmètre de la version 1.",
                                code="DEMARCHE_HORS_PERIMETRE")
    return valide.model_dump(mode="json"), definition.cle_doublon(valide, str(demandeur_id))


async def _dossier_ouvert_meme_cle(session: AsyncSession, cle: str, exclure: uuid.UUID | None = None) -> Dossier | None:
    requete = select(Dossier).where(Dossier.cle_doublon == cle, Dossier.statut.not_in(list(STATUTS_TERMINAUX)))
    if exclure:
        requete = requete.where(Dossier.id != exclure)
    return await session.scalar(requete.limit(1))


async def _erreur_doublon(session: AsyncSession, existant: Dossier) -> None:
    extra = {"reference_existante": existant.reference, "dossier_id": str(existant.id)}
    await session.rollback()  # annule aussi le demandeur et sa synchronisation éventuellement créés
    raise Conflit("Un dossier ouvert existe déjà pour cette demande.", code="DOUBLON_DETECTE", extra=extra)


def _pieces_manquantes(dossier: Dossier) -> list[DossierPieceRequise]:
    conformes = {p.code_piece for p in dossier.pieces_fournies if p.etat == EtatPiece.CONFORME}
    return [p for p in dossier.pieces_requises if p.obligatoire and p.code not in conformes]


def _sortie_pieces(pieces: list[DossierPieceRequise]) -> list[PieceRequiseDossierSortie]:
    return [PieceRequiseDossierSortie(code=p.code, libelle=p.libelle, obligatoire=p.obligatoire) for p in pieces]


async def charger(session: AsyncSession, dossier_id: uuid.UUID, courant: UtilisateurCourant) -> Dossier:
    dossier = await session.get(Dossier, dossier_id)
    if dossier is None or not peut_acceder(courant.role, courant.categorie, Categorie(dossier.categorie)):
        raise RessourceIntrouvable()  # on ne révèle pas l'existence d'un dossier hors périmètre
    return dossier


# --- UC03 Créer --------------------------------------------------------------------------------------

async def creer(session: AsyncSession, courant: UtilisateurCourant, donnees: DossierCreation) -> Dossier:
    _exiger(courant, Role.ACCUEIL)
    type_ = await _type_actif(session, donnees.type_demarche)
    demandeur = await _resoudre_demandeur(session, donnees.demandeur)
    donnees_json, cle = _valider_donnees(type_.code, donnees.donnees_specifiques, demandeur.id)

    existant = await _dossier_ouvert_meme_cle(session, cle)
    if existant is not None:
        if not donnees.confirmer_doublon:
            await _erreur_doublon(session, existant)
        if not donnees.motif_doublon:
            await session.rollback()
            raise RegleMetierViolee("Un motif est obligatoire pour créer un doublon.", code="MOTIF_OBLIGATOIRE")

    dossier = Dossier(
        reference=await _prochaine_reference(session), type_demarche=type_.code, categorie=type_.categorie,
        objet=donnees.objet, donnees_specifiques=donnees_json, cle_doublon=cle, statut=Statut.BROUILLON,
        demandeur_id=demandeur.id, createur_id=courant.id,
    )
    for ordre, piece in enumerate(p for p in type_.pieces if p.actif):
        dossier.pieces_requises.append(DossierPieceRequise(code=piece.code, libelle=piece.libelle,
                                                           obligatoire=piece.obligatoire, ordre=ordre))
    session.add(dossier)
    await session.flush()
    commentaire = "Dossier créé en brouillon"
    if existant is not None:
        commentaire += f" — doublon confirmé de {existant.reference} : {donnees.motif_doublon}"
    await _ajouter_historique(session, dossier, "CREATION", courant, nouveau=Statut.BROUILLON,
                              commentaire=commentaire)
    await session.commit()
    return dossier


# --- UC05 Lister ------------------------------------------------------------------------------------

async def lister(session: AsyncSession, courant: UtilisateurCourant, *, statut: Statut | None,
                 type_demarche: str | None, categorie: Categorie | None, reference: str | None,
                 demandeur: str | None, cree_du: date | None, cree_au: date | None,
                 page: int, taille: int) -> tuple[list[Dossier], int]:
    requete = select(Dossier).join(Demandeur, Dossier.demandeur_id == Demandeur.id)
    perimetre = courant.categorie_effective if courant.est_instructeur else None
    if perimetre:
        requete = requete.where(Dossier.categorie == perimetre)
    if statut:
        requete = requete.where(Dossier.statut == statut)
    if type_demarche:
        requete = requete.where(Dossier.type_demarche == type_demarche)
    if categorie:
        requete = requete.where(Dossier.categorie == categorie)
    if reference:
        requete = requete.where(Dossier.reference.ilike(f"%{reference}%"))
    if demandeur:
        motif = f"%{demandeur}%"
        requete = requete.where(or_(Demandeur.nom.ilike(motif), Demandeur.prenom.ilike(motif)))
    if cree_du:
        requete = requete.where(Dossier.cree_le >= datetime.combine(cree_du, time.min, UTC))
    if cree_au:
        requete = requete.where(Dossier.cree_le <= datetime.combine(cree_au, time.max, UTC))
    total = await session.scalar(select(func.count()).select_from(requete.subquery()))
    dossiers = await session.scalars(
        requete.order_by(Dossier.maj_le.desc()).offset((page - 1) * taille).limit(taille)
    )
    return list(dossiers.unique()), int(total or 0)


# --- UC06 Modifier ------------------------------------------------------------------------------------

async def modifier(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                   donnees: DossierModification) -> Dossier:
    _exiger(courant, Role.ACCUEIL)
    dossier = await charger(session, dossier_id, courant)
    if donnees.type_demarche is not None and donnees.type_demarche != dossier.type_demarche:
        raise ValidationEchouee(
            "Le type de démarche ne peut pas être modifié : annulez puis créez un nouveau dossier.",
            details=[{"champ": "type_demarche", "erreur": "non modifiable"}])
    if dossier.statut != Statut.BROUILLON:
        raise Conflit("Seul un dossier en brouillon peut être modifié.", code="ETAT_INCOMPATIBLE",
                      extra={"statut_courant": dossier.statut})
    if donnees.demandeur is not None:
        dossier.demandeur_id = (await _resoudre_demandeur(session, donnees.demandeur)).id
    if donnees.objet is not None:
        dossier.objet = donnees.objet
    brutes = donnees.donnees_specifiques if donnees.donnees_specifiques is not None else dossier.donnees_specifiques
    donnees_json, cle = _valider_donnees(dossier.type_demarche, brutes, dossier.demandeur_id)
    autre = await _dossier_ouvert_meme_cle(session, cle, exclure=dossier.id)
    if autre is not None:
        await _erreur_doublon(session, autre)
    dossier.donnees_specifiques = donnees_json
    dossier.cle_doublon = cle
    await _ajouter_historique(session, dossier, "MODIFICATION", courant, commentaire="Brouillon modifié")
    await session.commit()
    await session.refresh(dossier)
    return dossier


# --- UC07 / UC08 Pièces ---------------------------------------------------------------------------------

def _exiger_declarant(courant: UtilisateurCourant) -> None:
    _exiger(courant, Role.ACCUEIL, Role.AGENT_ETAT_CIVIL, Role.AGENT_CERTIFICATION)


def _exiger_statut_pieces(dossier: Dossier) -> None:
    if dossier.statut not in STATUTS_DECLARATION_PIECES:
        raise Conflit("Les pièces ne peuvent plus être modifiées dans ce statut.", code="ETAT_INCOMPATIBLE",
                      extra={"statut_courant": dossier.statut})


async def declarer_piece(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                         donnees: PieceDeclaration) -> PieceFournie:
    _exiger_declarant(courant)
    dossier = await charger(session, dossier_id, courant)
    _exiger_statut_pieces(dossier)
    requise = next((p for p in dossier.pieces_requises if p.code == donnees.code_piece), None)
    if requise is None:
        raise RegleMetierViolee("Ce type de pièce n'est pas prévu pour cette démarche.", code="PIECE_TYPE_INCONNU")
    if any(p.code_piece == donnees.code_piece and p.etat != EtatPiece.RETIREE for p in dossier.pieces_fournies):
        raise Conflit("Cette pièce est déjà déclarée : mettez-la à jour.", code="CONFLIT")
    piece = PieceFournie(dossier_id=dossier.id, code_piece=donnees.code_piece,
                         date_reception=donnees.date_reception, etat=donnees.etat,
                         observation=donnees.observation, declaree_par=courant.id)
    session.add(piece)
    etat = "conforme" if donnees.etat == EtatPiece.CONFORME else "à corriger"
    await _ajouter_historique(session, dossier, "PIECE_DECLAREE", courant,
                              commentaire=f"{requise.libelle} : {etat}")
    await session.commit()
    return piece


async def maj_piece(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                    piece_id: uuid.UUID, donnees: PieceMiseAJour) -> PieceFournie:
    _exiger_declarant(courant)
    dossier = await charger(session, dossier_id, courant)
    _exiger_statut_pieces(dossier)
    piece = next((p for p in dossier.pieces_fournies if p.id == piece_id), None)
    if piece is None:
        raise RessourceIntrouvable()
    if donnees.date_reception is not None:
        piece.date_reception = donnees.date_reception
    if donnees.etat is not None:
        piece.etat = donnees.etat
    if donnees.observation is not None:
        piece.observation = donnees.observation
    libelle = next((p.libelle for p in dossier.pieces_requises if p.code == piece.code_piece), piece.code_piece)
    await _ajouter_historique(session, dossier, "PIECE_MISE_A_JOUR", courant,
                              commentaire=f"{libelle} : {piece.etat}")
    await session.commit()
    return piece


async def verifier_completude(session: AsyncSession, courant: UtilisateurCourant,
                              dossier_id: uuid.UUID) -> VerificationSortie:
    _exiger(courant, Role.AGENT_ETAT_CIVIL, Role.AGENT_CERTIFICATION)
    dossier = await charger(session, dossier_id, courant)
    if dossier.statut not in (Statut.SOUMIS, Statut.INCOMPLET):
        raise Conflit("La complétude se vérifie sur un dossier soumis ou incomplet.", code="ETAT_INCOMPATIBLE",
                      extra={"statut_courant": dossier.statut})
    manquantes = _pieces_manquantes(dossier)
    if not manquantes:
        return VerificationSortie(complet=True, pieces_manquantes=[], statut=Statut(dossier.statut),
                                  transition_proposee=Statut.EN_INSTRUCTION)
    if dossier.statut == Statut.SOUMIS:
        motif = "Pièces manquantes ou à corriger : " + ", ".join(p.libelle for p in manquantes)
        await _changer_statut(session, dossier, courant, Statut.INCOMPLET, "BLOCAGE", motif[:500],
                              instruction=True)
        await session.commit()
    return VerificationSortie(complet=False, pieces_manquantes=_sortie_pieces(manquantes),
                              statut=Statut(dossier.statut), transition_proposee=None)


# --- UC09 Transitions --------------------------------------------------------------------------------------

async def _changer_statut(session: AsyncSession, dossier: Dossier, courant: UtilisateurCourant, nouveau: Statut,
                          type_evenement: str, commentaire: str | None, *, instruction: bool = False) -> None:
    ancien = Statut(dossier.statut)
    dossier.statut = nouveau
    if instruction and courant.est_instructeur:
        dossier.instructeur_id = courant.id
    numero = await _ajouter_historique(session, dossier, type_evenement, courant, ancien=ancien,
                                       nouveau=nouveau, commentaire=commentaire)
    await sync.projeter_transition(session, dossier, ancien, nouveau, numero)


async def transition(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                     statut_cible: Statut, motif: str | None, commentaire: str | None) -> Dossier:
    dossier = await charger(session, dossier_id, courant)
    actuel = Statut(dossier.statut)
    if statut_cible in STATUTS_PAR_DECISION:
        raise RegleMetierViolee("Une décision s'enregistre par /decision.", code="REGLE_METIER_VIOLEE")
    if statut_cible == Statut.ANNULE:
        raise RegleMetierViolee("Une annulation s'enregistre par /annulation.", code="REGLE_METIER_VIOLEE")
    regle = trouver_transition(actuel, statut_cible)
    if regle is None:
        raise Conflit(f"Transition interdite depuis {actuel}.", code="TRANSITION_INTERDITE",
                      extra={"statut_courant": actuel})
    if courant.role not in regle.roles:
        raise AccesRefuse()
    if regle.motif_obligatoire and not motif:
        raise RegleMetierViolee("Un motif est obligatoire pour cette transition.", code="MOTIF_OBLIGATOIRE")
    if regle.pieces_completes:
        manquantes = _pieces_manquantes(dossier)
        if manquantes:
            raise RegleMetierViolee(
                "Toutes les pièces requises doivent être présentes et conformes.", code="PIECES_INCOMPLETES",
                details=[{"champ": "pieces", "erreur": p.libelle} for p in manquantes])
    type_evenement = "BLOCAGE" if statut_cible == Statut.INCOMPLET else "TRANSITION"
    await _changer_statut(session, dossier, courant, statut_cible, type_evenement, motif or commentaire,
                          instruction=regle.instruction)
    await session.commit()
    await session.refresh(dossier)
    return dossier


# --- UC10 Décider -------------------------------------------------------------------------------------------

async def decider(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                  issue: IssueDecision, motif: str | None) -> Dossier:
    _exiger(courant, Role.RESPONSABLE)
    dossier = await charger(session, dossier_id, courant)
    if dossier.decision is not None:
        raise Conflit("Une décision est déjà enregistrée pour ce dossier.", code="DECISION_EXISTANTE")
    if dossier.statut != Statut.EN_ATTENTE_DECISION:
        raise Conflit("Le dossier n'est pas en attente de décision.", code="ETAT_INCOMPATIBLE",
                      extra={"statut_courant": dossier.statut})
    if get_settings().separation_instruction_decision and dossier.instructeur_id == courant.id:
        raise AccesRefuse("L'agent qui a instruit le dossier ne peut pas le décider (RM09).")
    if issue == IssueDecision.REJETE and not motif:
        raise RegleMetierViolee("Le motif est obligatoire pour un rejet.", code="MOTIF_OBLIGATOIRE")
    if _pieces_manquantes(dossier):
        raise RegleMetierViolee("Les pièces du dossier ne sont pas complètes.", code="PIECES_INCOMPLETES")
    session.add(Decision(dossier_id=dossier.id, issue=issue, motif=motif, auteur_id=courant.id))
    await _changer_statut(session, dossier, courant, Statut(issue), "DECISION", motif)
    await session.commit()
    await session.refresh(dossier)
    return dossier


# --- UC12 Annuler -------------------------------------------------------------------------------------------

async def annuler(session: AsyncSession, courant: UtilisateurCourant, dossier_id: uuid.UUID,
                  motif: str | None) -> Dossier:
    _exiger(courant, Role.ACCUEIL, Role.RESPONSABLE)
    dossier = await charger(session, dossier_id, courant)
    if dossier.statut not in STATUTS_ANNULABLES:
        raise Conflit(f"Un dossier {dossier.statut} ne peut pas être annulé.", code="TRANSITION_INTERDITE",
                      extra={"statut_courant": dossier.statut})
    if not motif:
        raise RegleMetierViolee("Le motif d'annulation est obligatoire.", code="MOTIF_OBLIGATOIRE")
    await _changer_statut(session, dossier, courant, Statut.ANNULE, "ANNULATION", motif)
    await session.commit()
    await session.refresh(dossier)
    return dossier


# --- UC11 Historique ----------------------------------------------------------------------------------------

async def historique(session: AsyncSession, courant: UtilisateurCourant,
                     dossier_id: uuid.UUID) -> list[EvenementHistorique]:
    await charger(session, dossier_id, courant)
    return list(await session.scalars(
        select(EvenementHistorique).where(EvenementHistorique.dossier_id == dossier_id)
        .order_by(EvenementHistorique.numero)
    ))
