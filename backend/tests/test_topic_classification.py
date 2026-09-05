from itertools import permutations
from unittest.mock import Mock

import pytest

from app.pipeline.analysis import classify_event, apply_langchain_result
from app.pipeline.langchain_analysis import HotspotAnalysisResult
from app.schemas import HotspotEventDTO, HotspotItem
from app.connectors.public_apis import DevCommunityConnector
from app.connectors.arxiv_ai import ArxivAIConnector


def event(title, source="hackernews", content="", tags=None):
    return HotspotEventDTO(event_key="topic-test", title=title, source_codes=[source], source_count=1,
                           items=[HotspotItem(source=source, source_name=source, title=title,
                                              content=content, tags=tags or [])])


@pytest.mark.parametrize("source", ["github", "hackernews", "devto"])
def test_ai_subject_is_not_overridden_by_host(source):
    assert classify_event(event("OpenAI launches a new reasoning agent", source)) == "AI / 大模型"


@pytest.mark.parametrize("title,expected", [
    ("PostgreSQL distributed storage improvements", "计算机技术"),
    ("Operating system kernel security vulnerability", "计算机技术"),
    ("Nvidia announces a new GPU chip", "科技产品"),
    ("GitHub 开源项目发布 SDK", "开源技术"),
])
def test_computing_and_product_topics(title, expected):
    assert classify_event(event(title)) == expected


def test_description_disambiguates_repository_name():
    assert classify_event(event("org/project", "github", "A neural inference model")) == "AI / 大模型"


def test_title_takes_precedence_over_generic_tags_and_description():
    assert classify_event(event("PostgreSQL database storage", "devto", "AI tools", ["AI"])) == "计算机技术"


def test_source_order_does_not_change_category():
    for sources in permutations(["github", "devto", "huggingface"]):
        item = event("New release")
        item.source_codes = list(sources)
        assert classify_event(item) == "AI / 大模型"


def test_arxiv_non_ai_fallback():
    item = event("A new approach", "arxiv_ai")
    item.items[0].raw_payload = {"primary_category": "cs.OS"}
    assert classify_event(item) == "计算机技术"


def test_generic_llm_category_does_not_erase_topic():
    result = apply_langchain_result(event("OpenAI agent update"), HotspotAnalysisResult(summary="update"), "AI")
    assert result.category == "AI / 大模型"


def test_dev_topics_include_computing():
    params = DevCommunityConnector().parameters()
    assert params["tag"] == "programming"


def test_arxiv_query_includes_systems_and_ai():
    connector = ArxivAIConnector()
    connector.get_text = Mock(return_value='<feed xmlns="http://www.w3.org/2005/Atom"/>')
    connector.fetch()
    query = connector.get_text.call_args.kwargs["params"]["search_query"]
    for category in ["cs.AI", "cs.DB", "cs.CR", "cs.OS", "cs.DC", "cs.NI"]:
        assert f"cat:{category}" in query
