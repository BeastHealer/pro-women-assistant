"""Конфигурация GigaChat."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class GigaConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GIGACHAT_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    credentials: str
    scope: str = "GIGACHAT_API_PERS"
    model_pro: str = "GigaChat-Pro"
    model_base: str = "GigaChat"
    max_retries: int = 3
    timeout: int = 60


giga_config = GigaConfig()
