from unittest.mock import Mock

import pytest
import requests
import yaml

from app.connectors.public_apis import GitHubAPIConnector, HuggingFaceConnector, DevCommunityConnector
from app.core.config import PROJECT_ROOT


@pytest.mark.parametrize("cls,data,identifier", [
    (GitHubAPIConnector, {"items": [{"id": 1, "full_name": "org/project", "description": "x" * 500, "owner": {"email": "private"}}]}, "1"),
    (HuggingFaceConnector, [{"id": "org/model", "downloads": 100, "author": "private", "cardData": {"secret": 1}}], "org/model"),
    (DevCommunityConnector, [{"id": 3, "title": "AI tools", "description": "x" * 500, "user": {"email": "private"}, "body_html": "full text"}], "3"),
])
def test_metadata_only(cls, data, identifier):
    connector = cls(max_items=1)
    connector.get_json = Mock(return_value=data)
    items = connector.fetch()
    assert len(items) == 1
    assert items[0].source_item_id == identifier
    assert items[0].url.startswith("https://")
    assert len(items[0].content) <= 300
    assert not {"owner", "author", "user", "body_html", "cardData"} & items[0].raw_payload.keys()
    assert items[0].raw_payload["real_source"] is True
    connector.get_json.assert_called_once()


@pytest.mark.parametrize("cls", [GitHubAPIConnector, HuggingFaceConnector, DevCommunityConnector])
def test_failure_stops_without_retry(cls):
    connector = cls()
    connector.get_json = Mock(side_effect=requests.HTTPError("429"))
    assert connector.fetch() == []
    connector.get_json.assert_called_once()


@pytest.mark.parametrize("cls", [GitHubAPIConnector, HuggingFaceConnector, DevCommunityConnector])
def test_zero_limit_does_not_request(cls):
    connector = cls(max_items=0)
    connector.get_json = Mock()
    assert connector.fetch() == []
    connector.get_json.assert_not_called()


def test_github_query_and_token(monkeypatch):
    monkeypatch.setenv("HOTSPOT_GITHUB_TOKEN", "test-token")
    connector = GitHubAPIConnector(max_items=200)
    params = connector.parameters()
    assert params["per_page"] == 100
    assert "pushed:>=" in params["q"]
    assert connector.headers["Authorization"] == "Bearer test-token"


def test_default_sources_and_registry():
    from app.agent.runner import build_connectors, CONNECTOR_REGISTRY
    from app.core.source_policy import OFFICIAL_SOURCE_CODES
    config = yaml.safe_load((PROJECT_ROOT / "config/sources.example.yml").read_text(encoding="utf-8"))
    assert set(CONNECTOR_REGISTRY) == OFFICIAL_SOURCE_CODES
    assert {c.source_code for c in build_connectors(config)} == {"github", "huggingface", "devto", "hackernews", "arxiv_ai"}


def test_bad_row_does_not_discard_good_rows():
    connector = DevCommunityConnector()
    connector.get_json = Mock(return_value=[None, {}, {"id": "bad", "title": "bad"}, {"id": 4, "title": "AI"}])
    assert [item.source_item_id for item in connector.fetch()] == ["4"]


def test_manual_api_defaults_and_rejects_legacy():
    from fastapi import HTTPException
    from app.api.hotspots import PlatformHotspotFetchPayload, fetch_platform_hotspots
    assert PlatformHotspotFetchPayload().sources == ["github", "huggingface", "devto"]
    with pytest.raises(HTTPException) as exc:
        fetch_platform_hotspots(PlatformHotspotFetchPayload(sources=["bilibili"]))
    assert exc.value.status_code == 400


def test_legacy_source_cannot_be_reenabled():
    from app.agent.runner import build_connectors
    with pytest.raises(ValueError, match="Unsupported source"):
        build_connectors({"sources": [{"code": "bilibili", "enabled": True}]})


def test_legacy_item_cannot_enter_storage():
    from app.pipeline.evidence import has_real_evidence
    from app.schemas import HotspotItem
    assert not has_real_evidence(HotspotItem(source="bilibili", source_name="legacy", title="AI", url="https://example.org/item"))
