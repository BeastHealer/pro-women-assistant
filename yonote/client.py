"""Клиент yonote.ru API (RPC v1, совместим с OpenAPI на yonote.ru/developers)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

import httpx

from .config import yonote_config

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class YonoteAPIError(Exception):
    """Ошибка ответа Yonote API."""

    def __init__(self, message: str, *, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class YonoteClient:
    """Клиент Documents / Collections / Database (v1)."""

    def __init__(self) -> None:
        self.base_url = yonote_config.base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {yonote_config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._property_map: dict[str, str] = dict(yonote_config.db_reports_props or {})
        self._property_map_inv: dict[str, str] = {v: k for k, v in self._property_map.items()}
        self._doc_id_cache: dict[str, str] = {}

    # ------------------------------------------------------------------ RPC
    @staticmethod
    def _clean_doc_ref(value: str) -> str:
        """Убрать query/fragment и взять последний сегмент URL/slug."""
        raw = (value or "").strip()
        if not raw:
            return raw
        raw = raw.split("?", 1)[0].split("#", 1)[0].strip().rstrip("/")
        if "://" in raw or "/" in raw:
            raw = raw.split("/")[-1]
        return raw

    async def resolve_document_id(self, doc_ref: str) -> str:
        """
        Привести ссылку/urlId/slug к UUID документа.

        В UI часто копируют ``slug-urlId`` или URL с ``?v=...``;
        ``database.rows.list`` требует UUID ``parentDocumentId``.
        """
        cleaned = self._clean_doc_ref(doc_ref)
        if not cleaned:
            raise YonoteAPIError("Empty document id")
        if _UUID_RE.match(cleaned):
            return cleaned
        if cleaned in self._doc_id_cache:
            return self._doc_id_cache[cleaned]

        doc = await self.get_document(cleaned)
        resolved = doc.get("id")
        if not resolved or not _UUID_RE.match(str(resolved)):
            raise YonoteAPIError(
                f"Cannot resolve document UUID from {doc_ref!r} (got {resolved!r})"
            )
        self._doc_id_cache[cleaned] = str(resolved)
        self._doc_id_cache[str(resolved)] = str(resolved)
        logger.info("Resolved Yonote doc %r -> %s", cleaned, resolved)
        return str(resolved)

    async def _request(
        self,
        method: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        raw: bool = False,
    ) -> Any:
        """
        POST ``{base_url}/{method}``.

        По умолчанию возвращает ``data`` из тела ``{ok, data}``.
        Для транзакций БД (``ok`` без ``data``) вернёт всё тело, если ``raw=True``.
        """
        url = f"{self.base_url}/{method.lstrip('/')}"
        body = payload or {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body, headers=self.headers)
            try:
                data = response.json()
            except Exception as exc:
                raise YonoteAPIError(
                    f"Invalid JSON from {method}: {response.status_code} {response.text[:300]}",
                    status=response.status_code,
                ) from exc

            if response.status_code >= 400:
                raise YonoteAPIError(
                    f"{method} HTTP {response.status_code}: {data.get('message') or data.get('error') or data}",
                    status=response.status_code,
                    payload=data,
                )

            if data.get("ok") is False:
                raise YonoteAPIError(
                    f"{method}: {data.get('error') or data.get('message') or data}",
                    status=response.status_code,
                    payload=data,
                )

            if raw:
                return data
            if "data" in data:
                return data["data"]
            return data

    def _resolve_prop_id(self, key: str) -> str:
        """Логическое имя колонки или UUID → UUID свойства."""
        if key in self._property_map:
            return self._property_map[key]
        # Уже UUID / неизвестный ключ — передаём как есть
        return key

    def _map_values(self, row: dict[str, Any]) -> dict[str, Any]:
        """Преобразовать {logical_name: value} → {propertyId: value}."""
        mapped: dict[str, Any] = {}
        for key, value in row.items():
            if key.startswith("_") or key == "title":
                continue
            prop_id = self._resolve_prop_id(key)
            # Колонка title в Yonote — заголовок строки, пишется отдельно
            if prop_id == "title":
                continue
            mapped[prop_id] = value
        return mapped

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Плоский dict: id + title + значения по логическим именам (если есть map)."""
        flat: dict[str, Any] = {
            "id": row.get("id"),
            "title": row.get("title") or "",
            "url": row.get("url"),
        }
        # group_name часто = системная колонка title
        if "group_name" in self._property_map and self._property_map["group_name"] == "title":
            flat["group_name"] = row.get("title") or ""
        values = row.get("values") or {}
        if isinstance(values, dict):
            for prop_id, value in values.items():
                name = self._property_map_inv.get(prop_id, prop_id)
                flat[name] = self._unwrap_value(value)
        # properties иногда приходят массивом с value внутри
        props = row.get("properties")
        if isinstance(props, list):
            for prop in props:
                if not isinstance(prop, dict):
                    continue
                prop_id = prop.get("id") or ""
                name = self._property_map_inv.get(prop_id, prop.get("title") or prop_id)
                if "value" in prop:
                    flat[name] = self._unwrap_value(prop.get("value"))
                elif "values" in prop:
                    flat[name] = self._unwrap_value(prop.get("values"))
        elif isinstance(props, dict):
            for prop_id, meta in props.items():
                name = self._property_map_inv.get(prop_id, prop_id)
                if prop_id == "title" or name == "title":
                    # уже в flat["title"] / group_name
                    continue
                if isinstance(meta, dict) and ("value" in meta or "values" in meta):
                    flat[name] = self._unwrap_value(meta.get("value", meta.get("values")))
                elif meta is not None and not isinstance(meta, dict):
                    flat[name] = self._unwrap_value(meta)
        return flat

    @staticmethod
    def _unwrap_value(value: Any) -> Any:
        if isinstance(value, dict) and "value" in value and len(value) <= 3:
            return value.get("value")
        if isinstance(value, list) and len(value) == 1:
            return YonoteClient._unwrap_value(value[0])
        return value

    @staticmethod
    def _extract_rows(data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            for key in ("rows", "documents", "data", "items"):
                nested = data.get(key)
                if isinstance(nested, list):
                    return [r for r in nested if isinstance(r, dict)]
            # один документ-строка
            if data.get("type") == "row" or data.get("id"):
                return [data]
        return []

    # === Documents =========================================================
    async def create_document(
        self,
        title: str,
        text: str,
        collection_id: Optional[str] = None,
        *,
        publish: bool = False,
    ) -> dict[str, Any]:
        """Создать документ (``documents.create``)."""
        payload: dict[str, Any] = {"title": title, "text": text}
        if collection_id:
            payload["collectionId"] = collection_id
        if publish:
            payload["publish"] = True
        result = await self._request("documents.create", payload)
        return result if isinstance(result, dict) else {"raw": result}

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        """Получить документ (``documents.info``)."""
        result = await self._request("documents.info", {"id": doc_id})
        return result if isinstance(result, dict) else {"raw": result}

    async def update_document(self, doc_id: str, text: str, title: Optional[str] = None) -> dict[str, Any]:
        """Обновить документ (``documents.update``)."""
        payload: dict[str, Any] = {"id": doc_id, "text": text}
        if title is not None:
            payload["title"] = title
        result = await self._request("documents.update", payload)
        return result if isinstance(result, dict) else {"raw": result}

    async def archive_document(self, doc_id: str) -> dict[str, Any]:
        """Архивировать документ (``documents.archive``)."""
        result = await self._request("documents.archive", {"id": doc_id})
        return result if isinstance(result, dict) else {"raw": result}

    # === Collections =======================================================
    async def list_collections(self) -> list[dict[str, Any]]:
        """Список коллекций (``collections.list``)."""
        result = await self._request("collections.list", {})
        if isinstance(result, list):
            return [c for c in result if isinstance(c, dict)]
        if isinstance(result, dict):
            nested = result.get("data") or result.get("collections")
            if isinstance(nested, list):
                return [c for c in nested if isinstance(c, dict)]
        return []

    # === Database ==========================================================
    async def database_transaction(
        self,
        database_id: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Атомарные изменения БД (``database/transaction``).

        Тело: ``{ "<databaseId>": [ {path, op, val}, ... ] }``.
        """
        db_uuid = await self.resolve_document_id(database_id)
        payload = {db_uuid: operations}
        result = await self._request("database/transaction", payload, raw=True)
        return result if isinstance(result, dict) else {"raw": result}

    async def add_db_row(
        self,
        db_id: str,
        row: dict[str, Any],
        *,
        title: Optional[str] = None,
        collection_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Создать строку через ``database/transaction`` (op=add + values).

        ``row`` — значения колонок: логические имена (из ``YONOTE_DB_REPORTS_PROPS``)
        или UUID свойств.
        """
        db_uuid = await self.resolve_document_id(db_id)
        row_id = str(uuid.uuid4())
        mapped = self._map_values(row)
        row_title = title or str(
            row.get("title")
            or row.get("group_name")
            or row.get("theme")
            or ""
        )
        coll = collection_id or yonote_config.db_reports_collection or None

        add_val: dict[str, Any] = {
            "_isNew": True,
            "id": row_id,
            "type": "row",
            "title": row_title,
            "parentDocumentId": db_uuid,
            "properties": {},
            "values": mapped,
            "tableOrder": 0,
        }
        if coll:
            add_val["collectionId"] = coll

        ops: list[dict[str, Any]] = [
            {"path": f"rows.{row_id}", "op": "add", "val": add_val},
        ]
        if row_title:
            ops.append(
                {"path": f"rows.{row_id}.title", "op": "update", "val": row_title}
            )
        if mapped:
            ops.append(
                {"path": f"rows.{row_id}.values", "op": "update", "val": mapped}
            )

        await self.database_transaction(db_uuid, ops)
        return {"id": row_id, "title": row_title, **{k: row[k] for k in row}}

    async def query_db(
        self,
        db_id: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
        *,
        order_by: Optional[str] = None,
        direction: str = "DESC",
    ) -> list[dict[str, Any]]:
        """
        Прочитать строки (``database.rows.list``).

        ``filters`` — ``{logical_name_or_uuid: value}`` → Yonote filter IsEquals.
        """
        db_uuid = await self.resolve_document_id(db_id)
        payload: dict[str, Any] = {
            # OpenAPI: parentDocumentId обязателен; id дублируем (schema required)
            "parentDocumentId": db_uuid,
            "id": db_uuid,
            "direction": direction if direction in ("ASC", "DESC") else "DESC",
        }
        if order_by:
            payload["orderBy"] = self._resolve_prop_id(order_by)

        yonote_filters: list[dict[str, Any]] = []
        for key, value in (filters or {}).items():
            yonote_filters.append(
                {
                    "filterPropertyId": self._resolve_prop_id(key),
                    "filterOperation": "IsEquals",
                    "filterValue": value,
                }
            )
        if yonote_filters:
            payload["filter"] = yonote_filters

        try:
            data = await self._request("database.rows.list", payload)
        except YonoteAPIError as exc:
            # Повтор без filter (часть инстансов капризничает на filter)
            if yonote_filters:
                logger.warning("database.rows.list with filter failed (%s), retry without", exc)
                payload.pop("filter", None)
                data = await self._request("database.rows.list", payload)
            else:
                raise

        rows = [self._normalize_row(r) for r in self._extract_rows(data)]

        # Клиентский фильтр (если API вернул всё / filter не сработал)
        if filters:
            filtered: list[dict[str, Any]] = []
            for r in rows:
                ok = True
                for key, expected in filters.items():
                    actual = r.get(key)
                    if actual is None:
                        actual = r.get(self._resolve_prop_id(key))
                    if str(actual) != str(expected):
                        ok = False
                        break
                if ok:
                    filtered.append(r)
            rows = filtered

        return rows[: int(limit)]

    async def update_db_row(
        self,
        db_id: str,
        row_id: str,
        data: dict[str, Any],
        *,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Обновить ячейки/заголовок строки через ``database/transaction``."""
        db_uuid = await self.resolve_document_id(db_id)
        ops: list[dict[str, Any]] = []
        if title is not None:
            ops.append({"path": f"rows.{row_id}.title", "op": "update", "val": title})
        mapped = self._map_values(data) if data else {}
        if mapped:
            ops.append({"path": f"rows.{row_id}.values", "op": "update", "val": mapped})
        if not ops:
            return {"id": row_id, "updated": False}
        await self.database_transaction(db_uuid, ops)
        return {"id": row_id, "updated": True, **data}

    async def delete_db_row(self, db_id: str, row_id: str) -> dict[str, Any]:
        """Удалить строку (``op=remove``)."""
        db_uuid = await self.resolve_document_id(db_id)
        await self.database_transaction(
            db_uuid,
            [{"path": f"rows.{row_id}", "op": "remove", "val": None}],
        )
        return {"id": row_id, "deleted": True}
