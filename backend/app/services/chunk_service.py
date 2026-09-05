"""文本切分服务。"""
from __future__ import annotations

import re


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")


def normalize_text(text: str) -> str:
    """清理文档文本，避免空白噪声影响 chunk 和 embedding。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text_into_chunks(text: str, chunk_size: int = 700, overlap: int = 100) -> list[str]:
    """把长文档切成适合向量检索的 chunk。

    第一版用字符数近似 token：
    - 中文 500-800 字一个 chunk，能保留完整语义。
    - overlap 80-120 字，避免切断上下文。
    - 优先按句号/问号/换行切，再兜底硬切。
    """
    text = normalize_text(text)
    if not text:
        return []

    chunk_size = max(200, int(chunk_size or 700))
    overlap = max(0, min(int(overlap or 100), chunk_size // 2))

    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if not sentences:
        sentences = [text]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(sentence):
                chunks.append(sentence[start : start + chunk_size].strip())
                start += chunk_size - overlap
            continue

        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current}\n{sentence}".strip() if current else sentence
        else:
            if current:
                chunks.append(current.strip())
                tail = current[-overlap:] if overlap else ""
                current = f"{tail}\n{sentence}".strip() if tail else sentence
            else:
                current = sentence

    if current:
        chunks.append(current.strip())

    # 去掉过短重复块，保留顺序。
    result: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        cleaned = normalize_text(chunk)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
