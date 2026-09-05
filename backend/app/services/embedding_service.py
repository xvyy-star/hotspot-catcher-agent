"""Embedding 服务。"""
from __future__ import annotations

import hashlib
import math
from typing import Iterable

import requests

from app.core.config import settings


class EmbeddingService:
    """统一 Embedding 接口。

    配置远程服务时固定使用远程向量，故障直接报错；未配置时使用独立的本地 hashing 模型。
    检索故障由知识库服务退回关键词查询，不切换向量算法。
    """

    def __init__(self) -> None:
        self.dimension = settings.embedding_dimension
        self.provider = "openai-compatible" if settings.embedding_base_url and settings.embedding_api_key else "local-hashing"
        self.model = settings.embedding_model if self.provider == "openai-compatible" else "local-hashing-v1"
        self.last_error: str | None = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "openai-compatible":
            try:
                self.last_error = None
                return self._embed_remote(texts)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                raise RuntimeError("Embedding service failed; vector space was not changed") from exc
        return [self._hashing_embedding(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        base_url = settings.embedding_base_url.rstrip("/")
        url = f"{base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": settings.embedding_model, "input": texts}
        resp = requests.post(url, headers=headers, json=payload, timeout=settings.embedding_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        rows = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [row.get("embedding") for row in rows]
        if (
            len(vectors) != len(texts)
            or [row.get("index") for row in rows] != list(range(len(texts)))
            or not vectors
            or not all(isinstance(vec, list) and vec and len(vec) == len(vectors[0]) for vec in vectors)
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                       for vec in vectors for value in vec)
        ):
            raise ValueError("Embedding API 返回结构不正确")
        self.dimension = len(vectors[0]) if vectors else self.dimension
        return vectors  # type: ignore[return-value]

    def _hashing_embedding(self, text: str) -> list[float]:
        """轻量 Hashing Embedding。

        它不是高质量语义向量，但优点是无模型、无下载、稳定可运行。
        交付说明：这是本地兜底；生产可替换 bge / OpenAI embedding。
        """
        dim = self.dimension
        vec = [0.0] * dim
        tokens = list(self._tokenize(text))
        if not tokens:
            tokens = [text or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (len(token) % 5) * 0.1
            vec[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [round(x / norm, 8) for x in vec]

    @staticmethod
    def _tokenize(text: str) -> Iterable[str]:
        buff = ""
        for ch in text.lower():
            if "\u4e00" <= ch <= "\u9fff":
                if buff:
                    yield buff
                    buff = ""
                yield ch
            elif ch.isalnum() or ch in {"_", "-"}:
                buff += ch
            else:
                if buff:
                    yield buff
                    buff = ""
        if buff:
            yield buff
