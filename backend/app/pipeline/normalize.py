"""文本清洗模块。"""
from __future__ import annotations

import re


PUNCT_RE = re.compile(r"[\s\t\r\n]+")
HASH_RE = re.compile(r"[#【】\[\]（）()]+")


def normalize_title(title: str) -> str:
    """清洗标题，为后续去重和分类提供更稳定的文本。

    这里不追求复杂 NLP，而是先解决最常见的噪声：
    - 话题井号
    - 多余空格
    - 平台装饰符号
    """
    text = HASH_RE.sub(" ", title or "")
    text = PUNCT_RE.sub(" ", text).strip()
    return text


def compact_key(title: str) -> str:
    """生成粗粒度 key，用于快速分桶，减少相似度比较次数。"""
    text = re.sub(r"\W+", "", normalize_title(title).lower())
    return text[:32] or "unknown"
