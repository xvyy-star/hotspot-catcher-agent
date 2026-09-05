"""跨平台热点去重模块。"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from app.pipeline.normalize import normalize_title
from app.schemas import HotspotEventDTO, HotspotItem

_STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "今日", "最新", "突发", "官方", "发布",
    "回应", "宣布", "一个", "一种", "关于", "视频", "全文", "直播",
}


def _tokenize(text: str) -> set[str]:
    normalized = normalize_title(text or "").lower()
    words = set(re.findall(r"[a-z0-9][a-z0-9_\-.]{1,}|[\u4e00-\u9fff]{2,}", normalized))
    # 中文没有分词依赖时补充 2-3 字符 ngram，增强“同一事件不同标题”的召回。
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    for size in (2, 3):
        for idx in range(max(0, len(cjk) - size + 1)):
            words.add(cjk[idx : idx + size])
    return {word for word in words if word not in _STOP_WORDS and len(word) >= 2}


def _event_text(item: HotspotItem) -> str:
    return " ".join([item.title or "", item.content or "", " ".join(item.tags or [])])


def similarity(a: str, b: str) -> float:
    """综合标题序列相似度与 token/ngram Jaccard，相比纯标题 SequenceMatcher 更稳。"""
    na = normalize_title(a)
    nb = normalize_title(b)
    seq_score = SequenceMatcher(None, na, nb).ratio()
    ta = _tokenize(na)
    tb = _tokenize(nb)
    if not ta or not tb:
        return seq_score
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(seq_score, 0.65 * jaccard + 0.35 * containment)


def build_event_key(title: str, tokens: set[str] | None = None) -> str:
    """生成事件唯一 key。

    优先用稳定 token 签名，标题轻微变化时仍能落到相近事件；
    token 不足时回退到标题 hash。
    """
    normalized = normalize_title(title)
    signature_tokens = sorted((tokens or _tokenize(normalized)))[:10]
    signature = "|".join(signature_tokens) if len(signature_tokens) >= 2 else normalized
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:24]


def _merge_score(item: HotspotItem, event: HotspotEventDTO) -> float:
    candidates = [event.title, event.summary or ""]
    candidates.extend(existing.title for existing in event.items[:5])
    item_text = _event_text(item)
    return max(similarity(item_text, candidate) for candidate in candidates if candidate)


def deduplicate_items(items: list[HotspotItem], threshold: float = 0.72) -> list[HotspotEventDTO]:
    """将多个平台的热点合并成事件。

    可交付版本不再只看单一标题相似度，而是综合标题、摘要、标签和字符 ngram；
    这能减少跨源同事件漏合并，也降低相似标题误合并。
    """
    events: list[HotspotEventDTO] = []
    for item in items:
        item_text = _event_text(item)
        title = normalize_title(item.title)
        matched: HotspotEventDTO | None = None
        best_score = 0.0
        for event in events:
            score = _merge_score(item, event)
            if score >= threshold and score > best_score:
                matched = event
                best_score = score
        if matched:
            matched.items.append(item)
            matched.source_codes = sorted({*matched.source_codes, item.source})
            matched.source_count = len(matched.source_codes)
            # 使用排名更靠前的平台标题作为主标题。
            if (item.rank or 9999) <= min((x.rank or 9999) for x in matched.items):
                matched.title = title
        else:
            tokens = _tokenize(item_text)
            events.append(
                HotspotEventDTO(
                    event_key=build_event_key(title, tokens),
                    title=title,
                    items=[item],
                    source_codes=[item.source],
                    source_count=1,
                )
            )
    return events
