"""Traduction en français des messages de validation génériques de Pydantic (CDC §5.7 : erreurs lisibles)."""

from typing import Any

_MESSAGES = {
    "missing": "Champ obligatoire.",
    "string_too_short": "Au moins {min_length} caractères.",
    "string_too_long": "Au plus {max_length} caractères.",
    "string_pattern_mismatch": "Format invalide.",
    "string_type": "Texte attendu.",
    "int_parsing": "Nombre entier attendu.",
    "int_type": "Nombre entier attendu.",
    "bool_parsing": "Valeur oui/non attendue.",
    "date_parsing": "Date invalide (format attendu : AAAA-MM-JJ).",
    "date_from_datetime_parsing": "Date invalide (format attendu : AAAA-MM-JJ).",
    "date_type": "Date invalide.",
    "datetime_parsing": "Date et heure invalides.",
    "uuid_parsing": "Identifiant invalide.",
    "greater_than_equal": "Doit être supérieur ou égal à {ge}.",
    "less_than_equal": "Doit être inférieur ou égal à {le}.",
    "greater_than": "Doit être supérieur à {gt}.",
    "less_than": "Doit être inférieur à {lt}.",
    "too_short": "Au moins {min_length} élément(s).",
    "too_long": "Au plus {max_length} élément(s).",
    "enum": "Valeur non autorisée.",
    "literal_error": "Valeur non autorisée.",
    "extra_forbidden": "Champ non autorisé.",
    "json_invalid": "Corps de requête JSON invalide.",
    "model_attributes_type": "Objet attendu.",
    "dict_type": "Objet attendu.",
    "list_type": "Liste attendue.",
}


def traduire(erreur: dict[str, Any]) -> str:
    """Message français d'une erreur Pydantic ; les messages métier (value_error) sont déjà en français."""
    type_ = erreur.get("type", "")
    if type_ == "value_error":
        message = str(erreur.get("msg", ""))
        if "email" in message.lower():
            return "Adresse e-mail invalide."
        return message.removeprefix("Value error, ")
    modele = _MESSAGES.get(type_)
    if modele is None:
        return str(erreur.get("msg", "Valeur invalide."))
    try:
        return modele.format(**(erreur.get("ctx") or {}))
    except (KeyError, IndexError):
        return modele
