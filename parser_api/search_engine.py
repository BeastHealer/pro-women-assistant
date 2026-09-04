"""Semantic search over approved photos from tg_vk_parser SQLite + CLIP/FAISS."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Allow importing modules from sibling tg_vk_parser
def _default_parser_root() -> Path:
    env = os.getenv("TG_VK_PARSER_ROOT")
    if env:
        return Path(env)
    # Local monorepo: pro-women-assistant/parser_api → ../../tg_vk_parser
    here = Path(__file__).resolve()
    if len(here.parents) >= 3:
        return here.parents[2] / "tg_vk_parser"
    return Path("/app/tg_vk_parser")


_DEFAULT_PARSER_ROOT = _default_parser_root()


def _ensure_parser_on_path(parser_root: Path) -> None:
    root = str(parser_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


class ArchiveSearchEngine:
    """CLIP text→image search over approved pipeline_images + FAISS archive index."""

    def __init__(
        self,
        db_path: str | Path,
        parser_root: Optional[str | Path] = None,
        index_path: Optional[str | Path] = None,
        metadata_path: Optional[str | Path] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.parser_root = Path(parser_root or _DEFAULT_PARSER_ROOT)
        data_dir = self.parser_root / "data"
        self.index_path = Path(
            index_path or os.getenv("ARCHIVE_INDEX_PATH", data_dir / "archive_index.faiss")
        )
        self.metadata_path = Path(
            metadata_path
            or os.getenv("ARCHIVE_METADATA_PATH", data_dir / "archive_metadata.json")
        )
        self.model_name = model_name or os.getenv(
            "CLIP_MODEL_NAME", "openai/clip-vit-base-patch32"
        )
        self.device = "cpu"
        self.model = None
        self.processor = None
        self.index = None
        self.metadata: list[dict[str, Any]] = []
        self._clip_loaded = False

    # ------------------------------------------------------------------ DB
    def connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def count_approved(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pipeline_images WHERE status = 'approved'"
            ).fetchone()
        return int(row["cnt"])

    def fetch_approved(
        self,
        *,
        author: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["status = 'approved'"]
        params: list[Any] = []
        if author:
            clauses.append("(author_name LIKE ? OR author_id LIKE ?)")
            like = f"%{author}%"
            params.extend([like, like])
        if date_from:
            clauses.append("published_at >= ?")
            params.append(date_from)
        if date_to:
            end = date_to if "T" in date_to else f"{date_to}T23:59:59"
            clauses.append("published_at <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        sql = f"""
            SELECT id, file_path, filename, author_id, author_name,
                   published_at, caption, status, decision_source, similarity_score
            FROM pipeline_images
            WHERE {where}
            ORDER BY published_at DESC, id DESC
        """
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, photo_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, file_path, filename, author_id, author_name,
                       published_at, caption, status, decision_source, similarity_score
                FROM pipeline_images WHERE id = ?
                """,
                (photo_id,),
            ).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            by_status = {
                r["status"]: r["cnt"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM pipeline_images GROUP BY status"
                )
            }
            top_authors = [
                {"author": r["author_name"], "count": r["cnt"]}
                for r in conn.execute(
                    """
                    SELECT author_name, COUNT(*) AS cnt
                    FROM pipeline_images
                    WHERE status = 'approved' AND author_name IS NOT NULL
                      AND TRIM(author_name) != ''
                    GROUP BY author_name
                    ORDER BY cnt DESC
                    LIMIT 10
                    """
                )
            ]
            dr = conn.execute(
                """
                SELECT MIN(published_at) AS d_from, MAX(published_at) AS d_to
                FROM pipeline_images WHERE status = 'approved'
                """
            ).fetchone()
        return {
            "by_status": by_status,
            "top_authors": top_authors,
            "date_range": {"from": dr["d_from"], "to": dr["d_to"]},
            "archive_index_ready": self.index_path.exists() and self.metadata_path.exists(),
            "archive_index_size": len(self.metadata) if self.metadata else None,
        }

    # --------------------------------------------------------------- CLIP
    def load_clip(self) -> None:
        if self._clip_loaded:
            return
        _ensure_parser_on_path(self.parser_root)
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        logger.info("Loading CLIP %s on %s", self.model_name, self.device)
        self.processor = CLIPProcessor.from_pretrained(self.model_name)
        self.model = CLIPModel.from_pretrained(
            self.model_name,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        )
        self.model.to(self.device)
        self.model.eval()
        self._clip_loaded = True

    def load_index(self) -> bool:
        if not self.index_path.exists() or not self.metadata_path.exists():
            return False
        import faiss

        self.index = faiss.read_index(str(self.index_path))
        self.metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        logger.info("Loaded archive FAISS with %d vectors", self.index.ntotal)
        return True

    def _embed_text(self, text: str) -> np.ndarray:
        import torch

        self.load_clip()
        assert self.model is not None and self.processor is not None
        inputs = self.processor(
            text=[text],
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            output = self.model.get_text_features(**inputs)
            if hasattr(output, "pooler_output") and output.pooler_output is not None:
                feats = output.pooler_output
            elif torch.is_tensor(output):
                feats = output
            else:
                feats = output[0]
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)

    def _embed_images(self, paths: list[Path]) -> np.ndarray:
        import torch
        from PIL import Image

        self.load_clip()
        assert self.model is not None and self.processor is not None
        images = []
        valid: list[int] = []
        for i, path in enumerate(paths):
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                images.append(img)
                valid.append(i)
            except Exception as exc:
                logger.warning("Skip image %s: %s", path, exc)
        if not images:
            return np.zeros((len(paths), 512), dtype=np.float32)
        inputs = self.processor(images=images, return_tensors="pt")
        pixel = inputs["pixel_values"].to(self.device)
        with torch.no_grad():
            output = self.model.get_image_features(pixel_values=pixel)
            if hasattr(output, "pooler_output") and output.pooler_output is not None:
                feats = output.pooler_output
            elif torch.is_tensor(output):
                feats = output
            else:
                feats = output[0]
            feats = feats / feats.norm(dim=-1, keepdim=True)
        emb = feats.cpu().numpy().astype(np.float32)
        result = np.zeros((len(paths), emb.shape[1]), dtype=np.float32)
        for j, orig in enumerate(valid):
            result[orig] = emb[j]
        return result

    def rebuild_archive_index(self, batch_size: int = 4) -> dict[str, Any]:
        """Embed all approved photos into FAISS for semantic search."""
        import faiss

        rows = self.fetch_approved()
        if not rows:
            raise RuntimeError("No approved photos in pipeline_images")

        started = time.perf_counter()
        embeddings: list[np.ndarray] = []
        meta: list[dict[str, Any]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            paths = [Path(r["file_path"]) for r in batch]
            emb = self._embed_images(paths)
            for i, row in enumerate(batch):
                if np.linalg.norm(emb[i]) < 1e-8:
                    continue
                embeddings.append(emb[i])
                meta.append(
                    {
                        "pipeline_id": row["id"],
                        "file_path": row["file_path"],
                        "filename": row.get("filename"),
                        "author_name": row.get("author_name"),
                        "published_at": row.get("published_at"),
                        "caption": row.get("caption") or "",
                    }
                )
            logger.info("Archive index: %d / %d", min(start + batch_size, len(rows)), len(rows))

        if not embeddings:
            raise RuntimeError("No valid embeddings for archive index")

        matrix = np.vstack(embeddings).astype(np.float32)
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.index_path))
        self.metadata_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.index = index
        self.metadata = meta
        return {
            "indexed": len(meta),
            "dim": int(matrix.shape[1]),
            "index_path": str(self.index_path),
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        author: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Semantic CLIP+FAISS search with optional metadata filters.

        Returns (photos, mode) where mode is 'clip_faiss' or 'text_fallback'.
        """
        query = (query or "").strip()
        if not query:
            rows = self.fetch_approved(
                author=author, date_from=date_from, date_to=date_to, limit=limit
            )
            return [self._to_photo(r) for r in rows], "latest"

        # Try CLIP+FAISS
        try:
            if self.index is None and not self.load_index():
                raise RuntimeError("archive index missing")
            assert self.index is not None
            q_emb = self._embed_text(query)
            # Over-fetch then filter by author/date
            k = min(max(limit * 5, limit), int(self.index.ntotal) or 1)
            scores, indices = self.index.search(q_emb, k=k)
            photos: list[dict[str, Any]] = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self.metadata):
                    continue
                m = self.metadata[idx]
                if author:
                    name = (m.get("author_name") or "").lower()
                    if author.lower() not in name:
                        continue
                pub = m.get("published_at") or ""
                if date_from and pub < date_from:
                    continue
                if date_to:
                    end = date_to if "T" in date_to else f"{date_to}T23:59:59"
                    if pub and pub > end:
                        continue
                row = self.get_by_id(int(m["pipeline_id"]))
                if not row or row.get("status") != "approved":
                    continue
                photo = self._to_photo(row)
                photo["score"] = round(float(score), 4)
                photos.append(photo)
                if len(photos) >= limit:
                    break
            if photos:
                return photos, "clip_faiss"
        except Exception as exc:
            logger.warning("CLIP search failed, falling back to LIKE: %s", exc)

        # Fallback: caption / author LIKE
        like = f"%{query}%"
        clauses = [
            "status = 'approved'",
            "(caption LIKE ? OR author_name LIKE ? OR filename LIKE ?)",
        ]
        params: list[Any] = [like, like, like]
        if author:
            clauses.append("(author_name LIKE ? OR author_id LIKE ?)")
            a = f"%{author}%"
            params.extend([a, a])
        if date_from:
            clauses.append("published_at >= ?")
            params.append(date_from)
        if date_to:
            end = date_to if "T" in date_to else f"{date_to}T23:59:59"
            clauses.append("published_at <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, file_path, filename, author_id, author_name,
                       published_at, caption, status, decision_source, similarity_score
                FROM pipeline_images
                WHERE {where}
                ORDER BY published_at DESC, id DESC
                LIMIT ?
                """,
                [*params, int(limit)],
            ).fetchall()
        return [self._to_photo(dict(r)) for r in rows], "text_fallback"

    @staticmethod
    def _to_photo(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "file_path": row.get("file_path") or "",
            "date": row.get("published_at"),
            "author": row.get("author_name") or row.get("author_id"),
            "text": row.get("caption") or "",
            "status": row.get("status") or "approved",
            "filename": row.get("filename"),
            "decision_source": row.get("decision_source"),
            "score": row.get("score"),
        }


# Singleton for FastAPI
_engine: Optional[ArchiveSearchEngine] = None


def get_engine() -> ArchiveSearchEngine:
    global _engine
    if _engine is None:
        db = os.getenv(
            "PARSER_DB_PATH",
            str(_DEFAULT_PARSER_ROOT / "data" / "images.db"),
        )
        _engine = ArchiveSearchEngine(db_path=db)
        try:
            _engine.load_index()
        except Exception as exc:
            logger.info("Archive index not loaded yet: %s", exc)
    return _engine
