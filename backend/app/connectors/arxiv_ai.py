"""arXiv 计算机方向官方 API 采集器。"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from app.connectors.base import BaseConnector
from app.schemas import HotspotItem

logger = logging.getLogger(__name__)


class ArxivAIConnector(BaseConnector):
    """采集 arXiv CS/AI 相关最新论文。

    它不是社交平台热搜，但对“计算机行业热点捕手”很有价值：能提前看到
    AI、机器学习、自然语言处理等方向的新论文和技术趋势。
    """

    source_code = "arxiv_ai"
    source_name = "arXiv CS/AI"
    api_url = "https://export.arxiv.org/api/query"
    atom_ns = "{http://www.w3.org/2005/Atom}"
    arxiv_ns = "{http://arxiv.org/schemas/atom}"

    @staticmethod
    def _clean(text: str | None) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def fetch(self) -> list[HotspotItem]:
        try:
            params = {
                "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.CV OR cat:cs.DC OR cat:cs.DB OR cat:cs.CR OR cat:cs.OS OR cat:cs.NI",
                "start": 0,
                "max_results": self.max_items,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            xml_text = self.get_text(self.api_url, params=params)
            root = ET.fromstring(xml_text)
            entries = root.findall(f"{self.atom_ns}entry")
            items: list[HotspotItem] = []
            for idx, entry in enumerate(entries[: self.max_items], start=1):
                title = self._clean(entry.findtext(f"{self.atom_ns}title"))
                link = self._clean(entry.findtext(f"{self.atom_ns}id"))
                summary = self._clean(entry.findtext(f"{self.atom_ns}summary"))
                published = self._clean(entry.findtext(f"{self.atom_ns}published"))
                primary_category = entry.find(f"{self.arxiv_ns}primary_category")
                categories = [node.attrib.get("term", "") for node in entry.findall(f"{self.atom_ns}category")]
                categories = [cat for cat in categories if cat]
                primary = primary_category.attrib.get("term") if primary_category is not None else (categories[0] if categories else "cs")
                if not title:
                    continue
                items.append(
                    HotspotItem(
                        source=self.source_code,
                        source_name=self.source_name,
                        source_item_id=link or title,
                        title=title,
                        url=link,
                        rank=idx,
                        raw_hot_score=None,
                        content=summary,
                        tags=["计算机行业", "研究论文", primary, "官方API"],
                        captured_at=datetime.utcnow(),
                        raw_payload={
                            "published": published,
                            "categories": categories,
                            "primary_category": primary,
                            "source_url": self.api_url,
                            "query": params["search_query"],
                            "real_source": True,
                        },
                    )
                )
            return items
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv 官方 API 采集失败: %s", exc)
            return []
