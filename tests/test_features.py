"""Integration tests for multi-source, EPG automation, and management API."""

import pytest

from tunaar import m3u
from tunaar.app import create_app
from tunaar.config import Config

PLAYLIST = (
    '#EXTM3U url-tvg="http://epg/auto.xml"\n'
    '#EXTINF:-1 group-title="News",CNN\nhttp://x/cnn\n'
    '#EXTINF:-1 group-title="Sports",ESPN\nhttp://x/espn\n'
    '#EXTINF:-1,Orphan\nhttp://x/orphan\n'
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    cfg = Config(
        device_id="TEST1234",
        tuner_count=2,
        sources=[{"name": "Main", "url": "http://x/list.m3u"}],
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    return create_app(cfg)


@pytest.fixture
def client(app):
    return app.test_client()


def test_all_groups_listed(client):
    cfg = client.get("/api/config").get_json()
    assert set(cfg["all_groups"]) == {"News", "Sports", m3u.UNGROUPED}


def test_epg_auto_discovered_from_playlist(client):
    cfg = client.get("/api/config").get_json()
    assert "http://epg/auto.xml" in cfg["discovered_epg"]
    status = client.get("/api/status").get_json()
    # auto-discovery means the guide is considered configured without manual URLs
    assert status["epg"]["auto"] is True
    assert status["epg"]["sources"] >= 1


def test_group_include_filter(client, app):
    resp = client.post("/api/groups", json={"include": ["News"]})
    assert resp.status_code == 200
    names = [c["name"] for c in client.get("/api/channels").get_json()]
    assert names == ["CNN"]
    # persisted to config
    assert app.config["TUNAAR"].groups_include == ["News"]


def test_group_exclude_filter(client):
    client.post("/api/groups", json={"exclude": ["Sports", m3u.UNGROUPED]})
    names = [c["name"] for c in client.get("/api/channels").get_json()]
    assert names == ["CNN"]


def test_add_and_remove_source(client, app):
    resp = client.post("/api/sources", json={"name": "Second", "url": "http://x/2.m3u"})
    assert resp.status_code == 200
    assert len(app.config["TUNAAR"].sources) == 2

    resp = client.delete("/api/sources/1")
    assert resp.status_code == 200
    assert len(app.config["TUNAAR"].sources) == 1


def test_add_source_requires_url(client):
    assert client.post("/api/sources", json={"name": "x"}).status_code == 400


def test_set_epg_urls_and_toggle_auto(client, app):
    resp = client.post(
        "/api/epg", json={"epg_urls": ["http://manual/g.xml"], "epg_auto": False}
    )
    assert resp.status_code == 200
    cfg = app.config["TUNAAR"]
    assert cfg.epg_urls == ["http://manual/g.xml"]
    assert cfg.epg_auto is False
