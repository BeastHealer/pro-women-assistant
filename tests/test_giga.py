"""Тесты для GigaClient."""
import pytest
from giga.client import GigaClient


@pytest.mark.asyncio
async def test_simple_generation():
    """Проверяем, что генерация работает."""
    client = GigaClient()
    result = await client.generate(
        prompt="Напиши короткое приветствие для женского сообщества",
        max_tokens=100,
    )
    assert len(result.text) > 10
    assert result.tokens_used > 0
    print(f"\nGenerated: {result.text}")
    print(f"Tokens: {result.tokens_used}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_simple_generation())
    