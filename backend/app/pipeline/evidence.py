"""真实来源与证据准入工具。

这层是项目的数据闸门：任何进入 raw_item / event / briefing 的热点，
都必须来自真实 connector，且必须带可打开的原文 http(s) 链接。
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.schemas import HotspotItem
from app.core.source_policy import OFFICIAL_SOURCE_CODES


FAKE_SOURCE_CODES = {"sample", "demo", "mock", "fake", "placeholder", "test"}


def is_http_url(url: str | None) -> bool:
    """只接受可追溯的 http(s) 链接。"""
    if not url:
        return False
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_fallback_item(item: HotspotItem) -> bool:
    """判断某条数据是否为本地样例/模拟数据。"""
    payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
    source = str(item.source or "").strip().lower()
    return source in FAKE_SOURCE_CODES or bool(payload.get("is_fallback_sample"))


def has_real_evidence(item: HotspotItem) -> bool:
    """真实数据准入：非样例、非 mock，并且有 item 级原文链接。"""
    if item.source not in OFFICIAL_SOURCE_CODES or is_fallback_item(item):
        return False
    return is_http_url(item.url)


def mark_real_evidence(item: HotspotItem) -> HotspotItem:
    """给通过准入的数据补充可观测字段，方便前端/日志解释。"""
    payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
    item.raw_payload = {
        **payload,
        "real_source": True,
        "has_real_evidence": True,
        "evidence_url": item.url,
    }
    return item


def split_items_by_evidence(items: list[HotspotItem]) -> tuple[list[HotspotItem], int, int]:
    """返回：通过准入的数据、样例/模拟拦截数、缺少原文链接拦截数。"""
    accepted: list[HotspotItem] = []
    dropped_fallback = 0
    dropped_no_evidence = 0
    for item in items:
        if is_fallback_item(item):
            dropped_fallback += 1
            continue
        if not has_real_evidence(item):
            dropped_no_evidence += 1
            continue
        accepted.append(mark_real_evidence(item))
    return accepted, dropped_fallback, dropped_no_evidence
