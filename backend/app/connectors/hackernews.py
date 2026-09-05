"""Hacker News 官方 API 采集器。"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from app.connectors.base import BaseConnector
from app.schemas import HotspotItem

logger = logging.getLogger(__name__)


class HackerNewsConnector(BaseConnector):
    """采集 Hacker News Top Stories。

    选择原因：HN 提供公开 Firebase API，比解析网页更稳定；非常适合捕捉
    海外计算机行业、开源工具、AI 工具和开发者社区热点。
    """

    source_code = "hackernews"
    source_name = "Hacker News Top Stories"
    topstories_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    item_url = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

    def _pick_url(self, row: dict[str, Any]) -> str:
        item_id = row.get("id")
        return row.get("url") or f"https://news.ycombinator.com/item?id={item_id}"

    def _fetch_item(self, order: int, item_id: int) -> tuple[int, int, dict[str, Any] | None]:
        """并发拉取单条 HN item。

        HN topstories API 只返回 id 列表，详情需要逐条请求。如果串行请求 30 条，
        生成早报会被拖慢；这里用线程池并发，同时保留原始 order 以便还原排名。
        """
        try:
            row = self.get_json(self.item_url.format(item_id=item_id))
            return order, item_id, row if isinstance(row, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Hacker News item 采集失败，跳过 item_id=%s: %s", item_id, exc)
            return order, item_id, None

    def fetch(self) -> list[HotspotItem]:
        try:
            ids = self.get_json(self.topstories_url)
            if not isinstance(ids, list):
                raise ValueError("HN topstories 返回结构不是列表")

            items: list[HotspotItem] = []
            # HN Top Stories 是“列表 API + 单条详情 API”两段式。
            # 多取一些候选，单条失败跳过；并发请求避免拖慢整份早报。
            candidates = list(enumerate(ids[: self.max_items * 3], start=1))
            rows: list[tuple[int, int, dict[str, Any]]] = []
            max_workers = min(8, max(1, len(candidates)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(self._fetch_item, order, item_id) for order, item_id in candidates]
                for future in as_completed(futures):
                    order, item_id, row = future.result()
                    if row:
                        rows.append((order, item_id, row))

            for _, item_id, row in sorted(rows, key=lambda item: item[0]):
                if len(items) >= self.max_items:
                    break
                if not isinstance(row, dict):
                    continue
                title = (row.get("title") or "").strip()
                if not title:
                    continue
                score = row.get("score")
                descendants = row.get("descendants")
                rank = len(items) + 1
                items.append(
                    HotspotItem(
                        source=self.source_code,
                        source_name=self.source_name,
                        source_item_id=str(row.get("id") or item_id),
                        title=title,
                        url=self._pick_url(row),
                        rank=rank,
                        raw_hot_score=str(score or ""),
                        content=f"score={score or 0}, comments={descendants or 0}",
                        tags=["计算机行业", "海外开发者社区", "官方API"],
                        captured_at=datetime.utcnow(),
                        raw_payload={
                            "id": row.get("id"),
                            "by": row.get("by"),
                            "score": score,
                            "descendants": descendants,
                            "time": row.get("time"),
                            "source_url": self.topstories_url,
                            "item_api_url": self.item_url.format(item_id=item_id),
                            "real_source": True,
                        },
                    )
                )
            return items
        except Exception as exc:  # noqa: BLE001
            # 真实模式下宁可返回空，也不伪造 HN 热点。
            logger.warning("Hacker News 官方 API 采集失败: %s", exc)
            return []
