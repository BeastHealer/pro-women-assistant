"""Клиент для VK API."""
import logging
from typing import Optional

import httpx

from .config import vk_config

logger = logging.getLogger(__name__)


class VKClient:
    """Клиент для работы с VK API."""

    def __init__(self):
        self.base_url = "https://api.vk.com/method"
        self.default_params = {
            "access_token": vk_config.access_token,
            "v": vk_config.api_version,
        }

    async def _call(self, method: str, params: dict) -> dict:
        """Вызвать метод VK API."""
        params = {**self.default_params, **params}
        url = f"{self.base_url}/{method}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=params)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                logger.error(f"VK API error: {data['error']}")
                raise Exception(f"VK API error: {data['error']}")

            return data.get("response", {})

    # === Публикация в открытую группу ===
    async def publish_post(
        self,
        text: str,
        attachments: Optional[list[str]] = None,
    ) -> int:
        """Опубликовать пост в открытую группу."""
        params = {
            "owner_id": f"-{vk_config.open_group_id}",
            "from_group": 1,
            "message": text,
        }
        if attachments:
            params["attachments"] = ",".join(attachments)

        result = await self._call("wall.post", params)
        post_id = result.get("post_id")
        logger.info(f"Published post {post_id} to open group")
        return post_id

    # === Работа с обсуждениями закрытой группы ===
    async def create_board_topic(
        self,
        title: str,
        text: str,
    ) -> int:
        """Создать тему в обсуждениях закрытой группы."""
        params = {
            "group_id": vk_config.closed_group_id,
            "title": title,
            "text": text,
        }
        result = await self._call("board.addTopic", params)
        topic_id = result.get("topic_id")
        logger.info(f"Created topic {topic_id} in closed group")
        return topic_id

    async def add_board_comment(
        self,
        topic_id: int,
        text: str,
    ) -> int:
        """Добавить комментарий в обсуждение."""
        params = {
            "group_id": vk_config.closed_group_id,
            "topic_id": topic_id,
            "message": text,
        }
        result = await self._call("board.createComment", params)
        return result.get("comment_id")

    async def create_poll(
        self,
        question: str,
        options: list[str],
        owner_id: Optional[str] = None,
    ) -> int:
        """Создать опрос."""
        params = {
            "owner_id": owner_id or f"-{vk_config.closed_group_id}",
            "question": question,
            "is_anonymous": 0,
            "add_answers": '["' + '","'.join(options) + '"]',
        }
        result = await self._call("polls.create", params)
        poll_id = result.get("id")
        logger.info(f"Created poll {poll_id}")
        return poll_id

    # === Работа с комментариями к постам ===
    async def get_comments(self, post_id: int, count: int = 100) -> list:
        """Получить комментарии к посту."""
        params = {
            "owner_id": f"-{vk_config.open_group_id}",
            "post_id": post_id,
            "count": count,
        }
        result = await self._call("wall.getComments", params)
        return result.get("items", [])

    async def delete_comment(self, comment_id: int) -> bool:
        """Удалить комментарий."""
        params = {
            "owner_id": f"-{vk_config.open_group_id}",
            "comment_id": comment_id,
        }
        await self._call("wall.deleteComment", params)
        return True
        