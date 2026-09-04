"""FastAPI wrapper for tg_vk_parser approved photo archive (CLIP + FAISS)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from search_engine import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PRO Women Photo Parser API",
    description="Семантический поиск по одобренным фото (pipeline_images + CLIP/FAISS)",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Photo(BaseModel):
    id: str
    file_path: str
    date: Optional[str] = None
    author: Optional[str] = None
    text: Optional[str] = None
    status: str
    filename: Optional[str] = None
    decision_source: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    query: str
    total: int
    mode: str = Field(description="clip_faiss | text_fallback | latest")
    photos: list[Photo]


@app.get("/health")
async def health() -> dict[str, Any]:
    """Проверка БД и индекса."""
    try:
        engine = get_engine()
        count = engine.count_approved()
        index_ok = engine.index_path.exists() and engine.metadata_path.exists()
        return {
            "status": "ok",
            "approved_photos": count,
            "db_path": str(engine.db_path),
            "archive_index": "ready" if index_ok else "missing",
            "table": "pipeline_images",
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/search", response_model=SearchResponse)
async def semantic_search(
    q: str = Query(..., description="Текстовый запрос (семантика CLIP)"),
    limit: int = Query(5, ge=1, le=50),
    author: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> SearchResponse:
    """Семантический поиск по approved (CLIP+FAISS, fallback LIKE по caption)."""
    engine = get_engine()
    try:
        photos, mode = engine.search(
            q,
            limit=limit,
            author=author,
            date_from=date_from,
            date_to=date_to,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SearchResponse(
        query=q,
        total=len(photos),
        mode=mode,
        photos=[Photo(**p) for p in photos],
    )


@app.get("/latest", response_model=list[Photo])
async def latest_photos(limit: int = Query(10, ge=1, le=50)) -> list[Photo]:
    """Последние одобренные фото."""
    engine = get_engine()
    rows = engine.fetch_approved(limit=limit)
    return [Photo(**engine._to_photo(r)) for r in rows]


@app.get("/stats")
async def stats() -> dict[str, Any]:
    """Статистика архива pipeline_images."""
    try:
        return get_engine().stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/admin/rebuild-index")
async def rebuild_index(
    batch_size: int = Query(4, ge=1, le=16),
) -> dict[str, Any]:
    """Пересобрать FAISS-индекс по всем approved (долго, нужен CLIP)."""
    engine = get_engine()
    try:
        result = engine.rebuild_archive_index(batch_size=batch_size)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.exception("rebuild-index failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/photo/{photo_id}/image")
async def get_photo_image(photo_id: str) -> FileResponse:
    """Вернуть файл изображения."""
    engine = get_engine()
    try:
        pid = int(photo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="photo_id must be int") from exc
    row = engine.get_by_id(pid)
    if not row:
        raise HTTPException(status_code=404, detail="Photo not found")
    file_path = Path(row["file_path"])
    # Fallback: approved_images copy
    if not file_path.is_file():
        alt = engine.parser_root / "data" / "approved_images" / Path(row["file_path"]).name
        if alt.is_file():
            file_path = alt
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return FileResponse(file_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
