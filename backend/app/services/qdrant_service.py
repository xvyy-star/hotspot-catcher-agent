"""Qdrant 向量库服务。"""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


class QdrantService:
    """Qdrant REST 客户端封装。"""

    def __init__(self, collection: str | None = None) -> None:
        self.base_url = settings.qdrant_url.rstrip("/")
        self.collection = collection or settings.qdrant_collection

    def health(self) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/collections/{self.collection}", timeout=5)
            if resp.status_code == 404:
                return {"ok": False, "status": "COLLECTION_NOT_FOUND", "url": self.base_url, "collection": self.collection}
            resp.raise_for_status()
            return {"ok": True, "status": "OK", "url": self.base_url, "collection": self.collection, "data": resp.json()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "ERROR", "url": self.base_url, "collection": self.collection, "message": str(exc)}

    def ensure_collection(self, vector_size: int) -> None:
        resp = requests.get(f"{self.base_url}/collections/{self.collection}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            current_size = (
                ((data.get("result") or {}).get("config") or {})
                .get("params", {})
                .get("vectors", {})
                .get("size")
            )
            if current_size and int(current_size) != int(vector_size):
                raise ValueError(
                    f"Qdrant collection 维度不匹配：{self.collection} 当前是 {current_size} 维，"
                    f"新 embedding 是 {vector_size} 维。请更换 QDRANT_COLLECTION，或使用重建 collection。"
                )
            return
        if resp.status_code != 404:
            resp.raise_for_status()
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        create_resp = requests.put(f"{self.base_url}/collections/{self.collection}", json=payload, timeout=30)
        create_resp.raise_for_status()

    def delete_collection(self) -> None:
        """删除当前 collection。

        只在用户明确触发 reindex 且 recreate_collection=true 时使用。
        """
        resp = requests.delete(f"{self.base_url}/collections/{self.collection}", timeout=30)
        if resp.status_code not in {200, 202, 404}:
            resp.raise_for_status()

    def recreate_collection(self, vector_size: int) -> None:
        self.delete_collection()
        self.ensure_collection(vector_size)

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        payload = {"points": points}
        resp = requests.put(
            f"{self.base_url}/collections/{self.collection}/points?wait=true",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()

    def search(
        self,
        vector: list[float],
        limit: int = 5,
        score_threshold: float | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        if document_ids:
            payload["filter"] = {
                "must": [
                    {"key": "document_id", "match": {"any": [int(item) for item in document_ids]}},
                ]
            }
        resp = requests.post(f"{self.base_url}/collections/{self.collection}/points/search", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("result") or []

    def delete_by_document(self, document_id: int) -> None:
        payload = {
            "filter": {
                "must": [
                    {"key": "document_id", "match": {"value": int(document_id)}},
                ]
            }
        }
        resp = requests.post(
            f"{self.base_url}/collections/{self.collection}/points/delete?wait=true",
            json=payload,
            timeout=30,
        )
        if resp.status_code not in {200, 404}:
            resp.raise_for_status()
