"""Configuration de l'application web, lue depuis l'environnement ou le fichier .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigWeb(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      env_ignore_empty=True)

    web_api_url: str = "http://127.0.0.1:8000/api/v1"
    web_secret_key: str | None = None
    web_sessions_dir: str = "instance/sessions"
    web_cookie_secure: bool = False
