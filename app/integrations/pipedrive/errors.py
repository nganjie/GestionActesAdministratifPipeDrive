"""Classification des erreurs Pipedrive (ISD §4.2)."""


class PipedriveErreur(Exception):
    relancable = False
    indetermine = False

    def __init__(self, code: str, message: str, *, status: int | None = None, retry_after: float | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"{code}: {message}")


class ErreurRelancable(PipedriveErreur):
    """429, 5xx : relance automatique bornée."""

    relancable = True


class ErreurIndeterminee(ErreurRelancable):
    """Timeout ou coupure : l'opération a peut-être abouti (contrôle d'existence avant relance)."""

    indetermine = True


class ErreurDefinitive(PipedriveErreur):
    """400, 401, 402, 403, 410, 422, réponse inattendue : aucune relance automatique."""


class RessourceAbsente(PipedriveErreur):
    """404 : objet supprimé dans Pipedrive (recréation contrôlée sur mise à jour)."""


class NonConfigure(ErreurDefinitive):
    def __init__(self) -> None:
        super().__init__("PIPEDRIVE_NON_CONFIGURE", "Le jeton Pipedrive n'est pas configuré.")
