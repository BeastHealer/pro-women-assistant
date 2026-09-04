"""Конфигурация VK API."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class VKConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VK_",
        env_file=".env",
        extra="ignore",
    )

    access_token: str
    open_group_id: str
    closed_group_id: str
    confirmation_code: str = ""
    api_version: str = "5.199"


vk_config = VKConfig()
