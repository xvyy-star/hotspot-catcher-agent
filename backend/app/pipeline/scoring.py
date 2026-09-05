"""热度评分模块。"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from app.schemas import HotspotEventDTO


DEFAULT_SOURCE_WEIGHTS = {
    "github": 0.88,
    "huggingface": 0.84,
    "devto": 0.72,
    "hackernews": 0.86,
    "arxiv_ai": 0.82,
}

DOMAIN_KEYWORDS = {
    "ai": 10,
    "agent": 8,
    "openai": 9,
    "大模型": 10,
    "模型": 6,
    "人工智能": 9,
    "芯片": 8,
    "半导体": 8,
    "开源": 7,
    "github": 8,
    "开发者": 6,
    "云": 4,
    "算力": 8,
    "机器人": 6,
    "安全": 6,
    "漏洞": 7,
    "产品": 4,
}

NOISE_KEYWORDS = {"明星", "综艺", "恋情", "八卦", "电视剧", "电影", "演唱会", "游戏主播"}


def _raw_heat_number(value: str | None) -> float:
    if not value:
        return 0
    text = str(value).replace(",", "").strip().lower()
    # Legacy arXiv rows used the publication timestamp as a heat value.
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:t|\s|$)", text):
        return 0
    multiplier = 1.0
    if "万" in text:
        multiplier = 10_000
    elif "亿" in text:
        multiplier = 100_000_000
    elif "k" in text:
        multiplier = 1_000
    elif "m" in text:
        multiplier = 1_000_000
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) * multiplier if match else 0


def _recency_score(event: HotspotEventDTO) -> float:
    latest = max((item.captured_at for item in event.items), default=None)
    if not latest:
        return 6
    if latest.tzinfo is not None:
        latest = latest.astimezone(timezone.utc).replace(tzinfo=None)
    hours = max(0.0, (datetime.utcnow() - latest).total_seconds() / 3600)
    return max(0.0, 8 * math.exp(-hours / 36))


def _domain_score(event: HotspotEventDTO) -> float:
    text = " ".join([event.title, event.summary or "", " ".join(sum((item.tags for item in event.items), []))]).lower()
    score = 0.0
    for keyword, weight in DOMAIN_KEYWORDS.items():
        if keyword.lower() in text:
            score += weight
    if any(keyword in text for keyword in NOISE_KEYWORDS):
        score -= 18
    return max(-20, min(score, 24))


def score_events(events: list[HotspotEventDTO], source_weights: dict[str, float] | None = None) -> list[HotspotEventDTO]:
    """计算统一热度分。

    可交付版本从“热榜排名”升级为：排名 + 平台可信度 + 多源确认 + 原始热度 + 新鲜度 + 领域相关度。
    这样更适合 AI/科技情报，而不是简单复刻泛热搜。
    """
    weights = {**DEFAULT_SOURCE_WEIGHTS, **(source_weights or {})}
    for event in events:
        rank_scores = []
        platform_scores = []
        raw_scores = []
        for item in event.items:
            rank = item.rank or 50
            rank_scores.append(max(0, (80 - min(rank, 80)) / 80 * 38))
            platform_scores.append(weights.get(item.source, 0.7) * 22)
            raw_heat = 0 if item.source == "arxiv_ai" else _raw_heat_number(item.raw_hot_score)
            if raw_heat > 0:
                raw_scores.append(min(12, math.log10(raw_heat + 1) * 2.2))
        cross_platform_bonus = min(max(event.source_count - 1, 0) * 9, 18)
        domain_score = _domain_score(event)
        recency = _recency_score(event)
        event.heat_score = round(
            max(
                0,
                min(
                    100,
                    max(rank_scores or [0])
                    + (sum(platform_scores) / max(1, len(platform_scores)))
                    + (max(raw_scores) if raw_scores else 0)
                    + cross_platform_bonus
                    + recency
                    + domain_score,
                ),
            ),
            2,
        )
    return sorted(events, key=lambda e: e.heat_score, reverse=True)
