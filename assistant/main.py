"""Главный FastAPI-сервер Контент-ассистента."""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from content.generator import ContentGenerator
from vk.publisher import ContentPublisher, DraftPost
from yonote.client import YonoteClient
from yonote.config import yonote_config

PARSER_API_URL = os.getenv("PARSER_API_URL", "http://parser-api:8000").rstrip("/")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# === Модели для webhook'ов ===
class SenlerReport(BaseModel):
    """Отчёт от Senler."""
    user_id: int
    group_name: str
    meeting_date: str
    participants_count: int
    theme: str
    insights: str
    photos: list[str] = []


class SenlerWebhook(BaseModel):
    """Webhook от Senler."""
    type: str
    data: dict[str, Any]


# === Lifespan ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте."""
    logger.info("Starting PRO Women Content Assistant")
    yield
    logger.info("Shutting down PRO Women Content Assistant")


app = FastAPI(
    title="PRO Women Content Assistant",
    description="API для управления контент-пайплайном",
    version="1.0.0",
    lifespan=lifespan,
)


# === Зависимости ===
generator = ContentGenerator()
publisher = ContentPublisher()
yonote = YonoteClient()


# === Эндпоинты ===
@app.get("/health")
async def health():
    """Проверка работоспособности."""
    return {"status": "ok", "service": "content-assistant"}


# === 1. Приём отчётов от Senler ===
@app.post("/webhook/senler/report")
async def receive_report(report: SenlerReport, request: Request):
    """Приём отчёта малой группы от Senler."""
    # Проверка секрета
    secret = request.headers.get("X-Senler-Secret", "")
    if secret != os.getenv("SENLER_WEBHOOK_SECRET"):
        raise HTTPException(status_code=403, detail="Invalid secret")

    logger.info(f"Received report from {report.group_name}")

    # Сохраняем в yonote Database (database/transaction + rows.list API v1)
    try:
        saved = await yonote.add_db_row(
            db_id=yonote_config.db_reports,
            row={
                "group_name": report.group_name,
                "meeting_date": report.meeting_date,
                "participants_count": report.participants_count,
                "theme": report.theme,
                "insights": report.insights,
                "status": "новый",
                "created_at": datetime.now().isoformat(),
            },
            title=f"{report.group_name} — {report.meeting_date}",
        )
        return {"status": "ok", "message": "Report saved", "row_id": saved.get("id")}
    except Exception as e:
        logger.error(f"Failed to save report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === 2. Генерация дайджеста ===
@app.post("/generate/digest")
async def generate_digest():
    """Сгенерировать еженедельный дайджест."""
    logger.info("Starting weekly digest generation")

    # 2.1. Получить отчёты за неделю из yonote.ru
    try:
        # Для MVP: отчёты со статусом «новый»
        reports = await yonote.query_db(
            db_id=yonote_config.db_reports,
            filters={"status": "новый"},
            limit=20,
        )
    except Exception as e:
        # Fallback: пустой список
        logger.warning(f"Failed to query yonote, using empty reports: {e}")
        reports = []

    if not reports:
        logger.info("No reports found, creating announcement-style digest")
        reports = [{"theme": "Нет данных", "insights": "Лидеры пока не сдали отчёты"}]

    # 2.2. Запросить фото из parser API
    photos = []
    try:
        import httpx
        themes = " ".join([r.get("theme", "") for r in reports if isinstance(r, dict)])
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PARSER_API_URL}/search",
                params={"q": themes, "limit": 5},
            )
            if response.status_code == 200:
                photos = response.json().get("photos", [])
    except Exception as e:
        logger.warning(f"Failed to get photos from parser: {e}")

    # 2.3. Генерация текста
    digest_text = await generator.generate_digest(reports, photos)

    # 2.4. Создание черновика в yonote.ru
    try:
        doc = await yonote.create_document(
            title=f"Дайджест {datetime.now().strftime('%d.%m.%Y')}",
            text=digest_text,
            collection_id=yonote_config.collection_drafts,
        )
        doc_id = doc.get("id")
        doc_url = doc.get("url", "")
    except Exception as e:
        logger.error(f"Failed to create yonote document: {e}")
        doc_id = "fallback"
        doc_url = ""

    # 2.5. Публикация в закрытую группу для утверждения
    try:
        result = await publisher.publish_to_closed_group(
            DraftPost(
                title=f"Дайджест {datetime.now().strftime('%d.%m.%Y')}",
                text=digest_text,
                doc_url=doc_url,
                photos=[p.get("file_path") for p in photos[:3]] if photos else None,
            )
        )
    except Exception as e:
        logger.error(f"Failed to publish to closed group: {e}")
        result = {"status": "error", "detail": str(e)}

    return {
        "status": "success",
        "digest_text": digest_text,
        "doc_id": doc_id,
        "reports_count": len(reports),
        "photos_count": len(photos),
        "vk_result": result,
    }


# === 3. Утверждение и публикация ===
@app.post("/approve/{doc_id}")
async def approve_and_publish(doc_id: str):
    """Утвердить черновик и опубликовать в открытую группу."""
    try:
        # Получаем документ
        doc = await yonote.get_document(doc_id)
        text = doc.get("text", "")
        title = doc.get("title", "Пост")

        # Публикуем
        post_id = await publisher.publish_to_open_group(
            DraftPost(title=title, text=text)
        )

        # Архивируем документ
        await yonote.archive_document(doc_id)

        return {
            "status": "published",
            "post_id": post_id,
            "doc_id": doc_id,
        }
    except Exception as e:
        logger.error(f"Failed to approve and publish: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === 4. Статистика ===
@app.get("/stats")
async def stats():
    """Общая статистика сервиса."""
    return {
        "gigachat_tokens_used": generator.client_pro.total_tokens_used,
        "service": "content-assistant",
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
    