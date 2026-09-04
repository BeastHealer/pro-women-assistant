"""Асинхронный клиент GigaChat API с retry-логикой."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import giga_config

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Результат генерации."""
    text: str
    tokens_used: int
    model: str
    prompt_tokens: int
    completion_tokens: int


class GigaClient:
    """Клиент для работы с GigaChat API."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or giga_config.model_pro
        self._client = GigaChat(
            credentials=giga_config.credentials,
            scope=giga_config.scope,
            model=self.model,
            verify_ssl_certs=False,
        )
        self._total_tokens = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(self, messages: list, max_tokens: int, temperature: float) -> Chat:
        """Синхронный вызов API (оборачивается в asyncio.to_thread)."""
        return self._client.chat(
            Chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> GenerationResult:
        """Генерация текста."""
        messages = []
        if system_prompt:
            messages.append(Messages(role=MessagesRole.SYSTEM, content=system_prompt))
        messages.append(Messages(role=MessagesRole.USER, content=prompt))

        try:
            response = await asyncio.to_thread(
                self._call_api, messages, max_tokens, temperature
            )

            result = GenerationResult(
                text=response.choices[0].message.content,
                tokens_used=response.usage.total_tokens,
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
            self._total_tokens += result.tokens_used
            logger.info(
                f"Generated {result.tokens_used} tokens "
                f"(prompt: {result.prompt_tokens}, completion: {result.completion_tokens})"
            )
            return result

        except Exception as e:
            logger.error(f"GigaChat API error: {e}")
            raise

    @property
    def total_tokens_used(self) -> int:
        """Общее количество использованных токенов."""
        return self._total_tokens