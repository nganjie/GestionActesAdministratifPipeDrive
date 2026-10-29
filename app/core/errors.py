"""Erreurs applicatives et format d'erreur unique (FRS §7.2)."""

from typing import Any


class AppError(Exception):
    """Erreur renvoyée au client sous la forme {code, message, details, correlation_id}."""

    status_code = 500
    code = "ERREUR_INTERNE"
    message = "Une erreur inattendue est survenue."

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 details: list[dict[str, Any]] | None = None, extra: dict[str, Any] | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or []
        self.extra = extra or {}
        super().__init__(self.message)


class ValidationEchouee(AppError):
    status_code = 400
    code = "VALIDATION_ECHOUEE"
    message = "Certains champs sont invalides."


class NonAuthentifie(AppError):
    status_code = 401
    code = "NON_AUTHENTIFIE"
    message = "Authentification requise ou identifiants invalides."


class JetonExpire(NonAuthentifie):
    code = "JETON_EXPIRE"
    message = "Le jeton d'accès a expiré."


class AccesRefuse(AppError):
    status_code = 403
    code = "ACCES_REFUSE"
    message = "Vous n'avez pas les droits nécessaires pour cette opération."


class RessourceIntrouvable(AppError):
    status_code = 404
    code = "RESSOURCE_INTROUVABLE"
    message = "La ressource demandée est introuvable."


class Conflit(AppError):
    """409 : TRANSITION_INTERDITE, ETAT_INCOMPATIBLE, DOUBLON_DETECTE, DECISION_EXISTANTE..."""

    status_code = 409
    code = "CONFLIT"
    message = "L'opération est incompatible avec l'état actuel de la ressource."


class RegleMetierViolee(AppError):
    """422 : DEMARCHE_HORS_PERIMETRE, PIECES_INCOMPLETES, MOTIF_OBLIGATOIRE..."""

    status_code = 422
    code = "REGLE_METIER_VIOLEE"
    message = "Une règle métier n'est pas respectée."


class TropDeTentatives(AppError):
    status_code = 429
    code = "TROP_DE_TENTATIVES"
    message = "Trop de tentatives de connexion. Réessayez plus tard."


class PipedriveErreurApi(AppError):
    status_code = 502
    code = "PIPEDRIVE_ERREUR"
    message = "Pipedrive a renvoyé une erreur."


class PipedriveIndisponible(AppError):
    status_code = 503
    code = "PIPEDRIVE_INDISPONIBLE"
    message = "Pipedrive est momentanément indisponible."


class PipedriveNonConfigure(AppError):
    status_code = 503
    code = "PIPEDRIVE_NON_CONFIGURE"
    message = "L'intégration Pipedrive n'est pas configurée."


class PipedriveDelaiDepasse(AppError):
    status_code = 504
    code = "PIPEDRIVE_DELAI_DEPASSE"
    message = "Pipedrive n'a pas répondu dans le délai imparti."
