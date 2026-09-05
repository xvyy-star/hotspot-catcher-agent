"""
采集器基类。

所有平台都实现同一个 fetch() 方法，这样 Orchestrator 不需要知道每个平台怎么抓。
这叫策略模式/适配器模式，架构上体现：平台差异被封装在 Connector 内部。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

from app.schemas import HotspotItem

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    source_code: str = "base"
    source_name: str = "Base"

    def __init__(self, max_items: int = 50, timeout: int = 10):
        self.max_items = max_items
        self.timeout = timeout
        self.headers = {
            # 设置常规 UA 是为了提高公开页面请求成功率，不做登录绕过和验证码绕过。
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,application/xhtml+xml",
        }

    @abstractmethod
    def fetch(self) -> list[HotspotItem]:
        """采集热点列表。任何异常都应在子类内部处理，避免拖垮整个任务。"""

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """带超时的 JSON 请求封装。"""
        resp = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """带超时的文本请求封装。

        RSS、HTML 榜单这类数据源不是 JSON，所以单独提供文本请求方法。
        """
        resp = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        # 有些中文 RSS 未正确声明 charset，requests 会按 ISO-8859-1 猜测，导致标题乱码。
        # apparent_encoding 会结合内容特征重新判断，适合公开新闻/RSS 页面。
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
