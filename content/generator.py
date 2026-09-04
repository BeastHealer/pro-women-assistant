"""Генерация контента через GigaChat."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from giga.client import GigaClient

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Загрузить user-шаблон задачи из ``content/prompts/{name}.md``."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def load_system_prompt() -> str:
    """Загрузить системный промпт (роль, правила, пайплайн, модерация)."""
    path = PROMPTS_DIR / "system_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(f"System prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def load_style_guide() -> str:
    """Загрузить стилистический гайд бренда."""
    path = PROMPTS_DIR / "style_guide.txt"
    if not path.exists():
        raise FileNotFoundError(f"Style guide not found: {path}")
    return path.read_text(encoding="utf-8")


def build_system_prompt(*, include_style_guide: bool = True) -> str:
    """Собрать system message: system_prompt.txt [+ style_guide.txt]."""
    parts = [load_system_prompt().strip()]
    if include_style_guide:
        parts.append(
            "==================================================\n"
            "СТИЛИСТИЧЕСКИЙ ГАЙД (обязателен для всех публичных текстов)\n"
            "==================================================\n\n"
            + load_style_guide().strip()
        )
    return "\n\n".join(parts)


class ContentGenerator:
    """Генератор контента."""

    def __init__(self) -> None:
        self.client_pro = GigaClient(model="GigaChat-Pro")
        self.client_base = GigaClient(model="GigaChat")

    async def generate_digest(
        self,
        reports: list[dict],
        photos: Optional[list[dict]] = None,
    ) -> str:
        """Сгенерировать еженедельный дайджест."""
        reports_json = json.dumps(reports, ensure_ascii=False, indent=2)
        photos_context = ""
        if photos:
            photos_context = "\n".join(
                [
                    f"- {p.get('date')}, {p.get('author')}: {p.get('text', '')[:100]}"
                    for p in photos
                ]
            )

        prompt_template = load_prompt("digest")
        prompt = prompt_template.format(
            reports_json=reports_json,
            photos_context=photos_context or "(фото не подобраны)",
        )

        result = await self.client_pro.generate(
            prompt=prompt,
            system_prompt=build_system_prompt(include_style_guide=True),
            max_tokens=2500,
            temperature=0.7,
        )

        logger.info("Generated digest: %s tokens", result.tokens_used)
        return result.text

    async def generate_announcement(self, events: list[dict]) -> str:
        """Сгенерировать анонс мероприятий."""
        events_json = json.dumps(events, ensure_ascii=False, indent=2)
        prompt = f"Сгенерируй подборку анонсов на 2 недели:\n\n{events_json}"

        result = await self.client_pro.generate(
            prompt=prompt,
            system_prompt=build_system_prompt(include_style_guide=True),
            max_tokens=2000,
            temperature=0.6,
        )
        return result.text

    async def classify_comment(self, text: str) -> dict[str, Any]:
        """Классифицировать комментарий: spam / suspicious / ok."""
        prompt = f"""Классифицируй комментарий по правилам модерации из системного промпта.

Текст: "{text}"

Верни ТОЛЬКО JSON без пояснений:
{{
  "category": "SPAM" | "SUSPICIOUS" | "OK",
  "confidence": 0.0-1.0,
  "reason": "краткое объяснение"
}}"""

        result = await self.client_base.generate(
            prompt=prompt,
            system_prompt=build_system_prompt(include_style_guide=False),
            max_tokens=200,
            temperature=0.1,
        )

        try:
            return json.loads(result.text)
        except json.JSONDecodeError:
            return {"category": "OK", "confidence": 0.5, "reason": "parse error"}
