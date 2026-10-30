"""Configuration de l'application, lue exclusivement depuis l'environnement (CDC EF12, RG07)."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty : une variable laissée vide dans .env (ex. PIPEDRIVE_OWNER_ID=) vaut « non définie ».
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      env_ignore_empty=True)

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://actes:actes@localhost:5432/actes"
    cors_origins: list[str] = Field(default_factory=list)

    # Authentification des agents (FRS UC01)
    jwt_secret: SecretStr
    jwt_access_minutes: int = 30
    jwt_refresh_hours: int = 8
    login_max_echecs: int = 5
    login_blocage_minutes: int = 15

    # Compte administrateur créé au premier démarrage (FRS UC02)
    admin_identifiant: str | None = None
    admin_mot_de_passe: SecretStr | None = None
    admin_nom: str = "Administrateur"

    # Règle RM09
    separation_instruction_decision: bool = True

    # Intégration Pipedrive (ISD §2.1)
    pipedrive_base_url: str = "https://api.pipedrive.com"
    pipedrive_api_token: SecretStr | None = None
    pipedrive_pipeline_name: str = "Actes administratifs"
    pipedrive_owner_id: int | None = None
    pipedrive_connect_timeout: float = 3.0
    pipedrive_read_timeout: float = 10.0
    pipedrive_max_retries: int = 5

    # Worker de synchronisation
    sync_poll_interval: float = 5.0
    sync_worker_embarque: bool = False

    # Mode démonstration : autorise la réinitialisation complète (base + deals Pipedrive). Jamais en production.
    mode_demo: bool = False

    @field_validator("jwt_secret")
    @classmethod
    def _secret_assez_long(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET doit contenir au moins 32 caractères")
        return v

    @property
    def pipedrive_configure(self) -> bool:
        return bool(self.pipedrive_api_token and self.pipedrive_api_token.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
