"""产品定位相关性闸门。

真实不等于有价值：泛娱乐平台和综合热榜里会出现大量真实但不适合作为
AI / 计算机行业情报的内容。本模块把“有出处”和“符合项目主线”分开控制。
"""
from __future__ import annotations

import re

from app.schemas import HotspotEventDTO, HotspotItem


STRONG_TECH_SOURCES = {"github", "arxiv_ai", "huggingface", "devto"}
GENERAL_SOURCES = set()

TECH_KEYWORDS = {
    "distributed", "network", "networking", "kernel", "cloud", "storage",
    "algorithm", "algorithms", "operating system", "redis", "nvidia", "amd",
    "ai",
    "aigc",
    "agent",
    "llm",
    "agi",
    "openai",
    "chatgpt",
    "claude",
    "gemini",
    "deepseek",
    "qwen",
    "kimi",
    "gpt",
    "github",
    "python",
    "rust",
    "javascript",
    "typescript",
    "linux",
    "docker",
    "kubernetes",
    "api",
    "sdk",
    "software",
    "hardware",
    "programming",
    "compiler",
    "runtime",
    "browser",
    "database",
    "postgres",
    "postgresql",
    "sqlite",
    "server",
    "security",
    "vulnerability",
    "code",
    "coding",
    "developer",
    "web",
    "javascript",
    "typescript",
    "react",
    "vue",
    "svelte",
    "人工智能",
    "大模型",
    "智能体",
    "开源",
    "编程",
    "程序员",
    "开发者",
    "代码",
    "算法",
    "数据库",
    "芯片",
    "算力",
    "gpu",
    "cpu",
    "服务器",
    "云计算",
    "操作系统",
    "鸿蒙",
    "harmonyos",
    "自动驾驶",
    "机器人",
    "数据中心",
    "网络安全",
    "漏洞",
    "推理",
    "训练",
    "模型",
    "生成式",
}

NOISE_KEYWORDS = {
    "麻醉",
    "医学",
    "医生",
    "医院",
    "手术",
    "娱乐",
    "影视",
    "剪辑",
    "创业记",
    "游戏",
    "手游",
    "动漫",
    "番剧",
    "美食",
    "旅游",
    "高考",
    "中考",
    "考研",
}


def keyword_in_text(keyword: str, text: str) -> bool:
    """英文缩写必须按边界命中，避免 ai 命中 rain / daily / Mantz 之类噪声。"""
    normalized = keyword.lower()
    lowered = (text or "").lower()
    if re.fullmatch(r"[a-z0-9_+\-.]+", normalized):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", lowered))
    return normalized in lowered


def title_has_tech_signal(item: HotspotItem) -> bool:
    return any(keyword_in_text(keyword, item.title or "") for keyword in TECH_KEYWORDS)


def is_obvious_general_noise(item: HotspotItem) -> bool:
    text = f"{item.title or ''} {' '.join(item.tags or [])}"
    return any(keyword_in_text(keyword, text) for keyword in NOISE_KEYWORDS)


def item_matches_product_focus(item: HotspotItem) -> bool:
    if item.source in STRONG_TECH_SOURCES:
        return True
    if item.source in GENERAL_SOURCES and is_obvious_general_noise(item):
        return False
    # 泛热点源必须标题本身命中技术词，不能因为正文/标签里偶然出现 ai 字符串就放行。
    return title_has_tech_signal(item)


def event_matches_product_focus(event: HotspotEventDTO) -> bool:
    sources = set(event.source_codes or [])
    if sources & STRONG_TECH_SOURCES:
        return True
    if not sources:
        return False
    if sources.isdisjoint(GENERAL_SOURCES):
        return any(item_matches_product_focus(item) for item in event.items or [])
    return any(item_matches_product_focus(item) for item in event.items or [])


def filter_events_for_product_focus(events: list[HotspotEventDTO]) -> list[HotspotEventDTO]:
    return [event for event in events if event_matches_product_focus(event)]
