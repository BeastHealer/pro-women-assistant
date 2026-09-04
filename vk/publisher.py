"""Публикация контента в VK с учётом стиля PRO Женщин."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .client import VKClient

logger = logging.getLogger(__name__)


@dataclass
class DraftPost:
    """Черновик поста."""
    title: str
    text: str
    doc_url: Optional[str] = None
    photos: Optional[list[str]] = None


class ContentPublisher:
    """Публикатор контента в VK."""

    def __init__(self):
        self.vk = VKClient()

    async def publish_to_closed_group(self, draft: DraftPost) -> dict:
        """Опубликовать черновик в закрытую группу для утверждения."""
        # Формируем текст с ссылкой на документ
        message = f"📋 **{draft.title}**\n\n"
        message += draft.text[:1500] + ("..." if len(draft.text) > 1500 else "")
        message += "\n\n"
        if draft.doc_url:
            message += f"🔗 Полный текст: {draft.doc_url}\n"
        message += "\n👇 Голосуйте в опросе ниже"

        # Создаём тему в обсуждениях
        topic_id = await self.vk.create_board_topic(
            title=draft.title,
            text=message,
        )

        # Создаём опрос
        poll_id = await self.vk.create_poll(
            question=f"Утвердить пост «{draft.title}»?",
            options=[
                "✅ Утвердить без изменений",
                "🔧 Утвердить с правками",
                "❌ Отклонить",
            ],
        )

        # Добавляем опрос как комментарий к теме
        await self.vk.add_board_comment(
            topic_id=topic_id,
            text=f"Опрос для утверждения: poll-{poll_id}",
        )

        return {
            "topic_id": topic_id,
            "poll_id": poll_id,
            "status": "awaiting_approval",
        }

    async def publish_to_open_group(
        self,
        draft: DraftPost,
    ) -> int:
        """Опубликовать финальный пост в открытую группу."""
        post_id = await self.vk.publish_post(
            text=draft.text,
            attachments=draft.photos or [],
        )
        logger.info(f"Published to open group: post_id={post_id}")
        return post_id
        