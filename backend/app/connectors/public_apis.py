"""Official API collectors with bounded requests and metadata-only storage."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.connectors.base import BaseConnector
from app.schemas import HotspotItem

logger = logging.getLogger(__name__)


class PublicAPIConnector(BaseConnector):
    api_url = ""

    def parameters(self):
        raise NotImplementedError

    def rows(self, data):
        return data

    def to_item(self, row, rank):
        raise NotImplementedError

    def fetch(self) -> list[HotspotItem]:
        if self.max_items <= 0:
            return []
        self.headers.update({"User-Agent": "HotspotCatcher-GraduationProject/1.0", "Accept": "application/json"})
        try:
            rows = self.rows(self.get_json(self.api_url, params=self.parameters()))
            if not isinstance(rows, list):
                raise ValueError("Expected an API result list")
            items = []
            for rank, row in enumerate(rows[:min(self.max_items, 100)], 1):
                if not isinstance(row, dict):
                    continue
                try:
                    item = self.to_item(row, rank)
                    if item:
                        items.append(item)
                except (ValueError, TypeError, KeyError):
                    logger.warning("%s skipped malformed row %s", self.source_code, rank)
            return items
        except Exception as exc:
            # Denial or rate limiting ends this fetch; no retries or endpoint rotation.
            logger.warning("%s API fetch failed: %s", self.source_code, exc)
            return []

    def item(self, *, identifier, title, url, rank, score, content, tags, metadata):
        return HotspotItem(
            source=self.source_code, source_name=self.source_name,
            source_item_id=str(identifier), title=title, url=url, rank=rank,
            raw_hot_score=str(score or 0), content=(content or "")[:300], tags=tags,
            raw_payload={**metadata, "source_url": self.api_url, "real_source": True},
        )


class GitHubAPIConnector(PublicAPIConnector):
    source_code = "github"
    source_name = "GitHub AI Repositories"
    api_url = "https://api.github.com/search/repositories"

    def parameters(self):
        self.headers["X-GitHub-Api-Version"] = "2022-11-28"
        token = os.getenv("HOTSPOT_GITHUB_TOKEN", "").strip()
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        return {"q": f"topic:artificial-intelligence archived:false pushed:>={since}",
                "sort": "stars", "order": "desc", "per_page": min(self.max_items, 100)}

    def rows(self, data):
        return data["items"]

    def to_item(self, row, rank):
        name = row.get("full_name")
        if not name or not row.get("id") or row.get("private"):
            return None
        return self.item(identifier=row["id"], title=name,
                         url="https://github.com/" + quote(name, safe="/"), rank=rank,
                         score=row.get("stargazers_count"), content=row.get("description"),
                         tags=["AI", "open-source"], metadata={
                             "stars": row.get("stargazers_count", 0), "language": row.get("language"),
                             "published_at": row.get("created_at"), "updated_at": row.get("pushed_at"),
                             "metric": "total_stars", "selection": "AI topic; pushed within 30 days",
                         })


class HuggingFaceConnector(PublicAPIConnector):
    source_code = "huggingface"
    source_name = "Hugging Face Models"
    api_url = "https://huggingface.co/api/models"

    def parameters(self):
        return {"sort": "downloads", "direction": -1, "limit": min(self.max_items, 100)}

    def to_item(self, row, rank):
        name = row.get("id")
        if not name or row.get("private"):
            return None
        task = row.get("pipeline_tag") or "machine-learning"
        return self.item(identifier=name, title=name,
                         url="https://huggingface.co/" + quote(name, safe="/"), rank=rank,
                         score=row.get("downloads"), content=f"AI model; task: {task}",
                         tags=["AI", "model", task], metadata={
                             "downloads": row.get("downloads", 0), "likes": row.get("likes", 0),
                             "pipeline_tag": task, "updated_at": row.get("lastModified"),
                             "metric": "hub_downloads",
                         })


class DevCommunityConnector(PublicAPIConnector):
    source_code = "devto"
    source_name = "DEV Community AI & Computing"
    api_url = "https://dev.to/api/articles"

    def parameters(self):
        return {"tag": "programming", "top": 7, "per_page": min(self.max_items, 100)}

    def to_item(self, row, rank):
        if not row.get("id") or not row.get("title"):
            return None
        return self.item(identifier=row["id"], title=row["title"],
                         url=f"https://dev.to/a/{int(row['id'])}", rank=rank,
                         score=row.get("positive_reactions_count"), content=row.get("description"),
                         tags=["developer", *(tag for tag in (row.get("tag_list") or []) if isinstance(tag, str))][:8], metadata={
                             "published_at": row.get("published_at"),
                             "reactions": row.get("positive_reactions_count", 0),
                             "comments_count": row.get("comments_count", 0), "metric": "positive_reactions",
                         })
