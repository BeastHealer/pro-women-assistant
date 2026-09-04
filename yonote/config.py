"""Конфигурация yonote.ru API."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class YonoteConfig(BaseSettings):
    """
    Переменные с префиксом ``YONOTE_``.

    Документы/коллекции — UUID из UI Yonote.
    Database: ``db_reports`` = id документа типа database (parentDocumentId).
    ``db_reports_props`` — JSON-карта логических имён колонок → UUID свойств.
    """

    model_config = SettingsConfigDict(
        env_prefix="YONOTE_",
        env_file=".env",
        extra="ignore",
    )

    api_key: str
    base_url: str = "https://app.yonote.ru/api"
    collection_drafts: str
    db_reports: str
    # Коллекция, в которой лежит БД отчётов (нужна части API при создании row)
    db_reports_collection: str = ""
    # {"group_name": "<prop-uuid>", "status": "<prop-uuid>", ...}
    db_reports_props: dict[str, str] = Field(default_factory=dict)
    # Устарело: стиль в content/prompts/
    doc_style_guide: str = ""

    @field_validator("db_reports_props", mode="before")
    @classmethod
    def _parse_props(cls, value: Any) -> dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            import json

            data = json.loads(value)
            if not isinstance(data, dict):
                raise ValueError("YONOTE_DB_REPORTS_PROPS must be a JSON object")
            return {str(k): str(v) for k, v in data.items()}
        raise ValueError("YONOTE_DB_REPORTS_PROPS must be a JSON object")


yonote_config = YonoteConfig()
