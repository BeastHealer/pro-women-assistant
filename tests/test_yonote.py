"""Smoke-тесты yonote.ru API (нужен заполненный .env)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Подхватываем .env до импорта yonote.config / проверки skip
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", override=False)


def _has_yonote_env() -> bool:
    return bool(os.getenv("YONOTE_API_KEY") and os.getenv("YONOTE_COLLECTION_DRAFTS"))


@pytest.mark.skipif(not _has_yonote_env(), reason="YONOTE_* not configured")
@pytest.mark.asyncio
async def test_list_collections():
    from yonote.client import YonoteClient

    client = YonoteClient()
    collections = await client.list_collections()
    assert isinstance(collections, list)
    for c in collections[:5]:
        print(f"  - {c.get('name')} (id: {c.get('id')})")


@pytest.mark.skipif(not _has_yonote_env(), reason="YONOTE_* not configured")
@pytest.mark.asyncio
async def test_query_reports_db():
    from yonote.client import YonoteClient
    from yonote.config import yonote_config

    if not yonote_config.db_reports:
        pytest.skip("YONOTE_DB_REPORTS empty")

    client = YonoteClient()
    rows = await client.query_db(yonote_config.db_reports, limit=5)
    assert isinstance(rows, list)
    print(f"reports rows: {len(rows)}")
    if rows:
        print("sample keys:", sorted(rows[0].keys()))


if __name__ == "__main__":
    asyncio.run(test_list_collections())
