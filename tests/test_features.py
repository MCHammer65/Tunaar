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


def test_name_based_epg_match_for_channel_without_tvgid(tmp_path, monkeypatch):
    # A channel with no tvg-id (like a real HDHomeRun/OTA channel)…
    playlist = '#EXTM3U\n#EXTINF:-1,BBC One HD\nhttp://x/bbc\n'
    epg_xml = (
        b'<?xml version="1.0"?><tv>'
        b'<channel id="bbc1.uk"><display-name>BBC One</display-name></channel>'
        b'<programme start="20260101060000 +0000" channel="bbc1.uk"><title>News</title></programme>'
        b'</tv>'
    )
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: playlist)
    monkeypatch.setattr("tunaar.epg.fetch", lambda url, **k: epg_xml)

    cfg = Config(
        device_id="NAME1",
        sources=[{"name": "OTA", "url": "http://x/l.m3u"}],
        epg_urls=["http://x/guide.xml"],
        epg_auto=False,
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    app = create_app(cfg)
    client = app.test_client()

    status = client.get("/api/status").get_json()
    # …gets matched to the guide by name, so the guide is populated.
    assert status["epg"]["matched"] == 1
    assert status["epg"]["programmes"] == 1
    chan = client.get("/api/channels").get_json()[0]
    assert chan["tvg_id"] == "bbc1.uk"  # filled in by name match


def test_presets_listed_with_added_flag(client):
    presets = client.get("/api/presets").get_json()
    ids = {p["id"] for p in presets}
    assert {"samsung-gb", "pluto-gb", "samsung-us", "pluto-us",
            "samsung-ca", "pluto-ca", "samsung-fr", "pluto-fr", "jamaica"} <= ids
    assert all(p["added"] is False for p in presets)  # none added yet
    assert {"GB", "US", "CA", "FR", "JM"} <= {p["region"] for p in presets}


def test_add_preset_creates_source_and_marks_added(client):
    r = client.post("/api/sources", json={"preset": "samsung-gb"})
    sources = r.get_json()["sources"]
    assert sources[-1]["url"] == "https://i.mjh.nz/SamsungTVPlus/gb.m3u8"
    assert sources[-1]["group"] == "Samsung TV Plus"
    # Now the preset is reported as added and re-adding is idempotent.
    presets = {p["id"]: p for p in client.get("/api/presets").get_json()}
    assert presets["samsung-gb"]["added"] is True
    client.post("/api/sources", json={"preset": "samsung-gb"})
    urls = [s["url"] for s in client.get("/api/config").get_json()["sources"]]
    assert urls.count("https://i.mjh.nz/SamsungTVPlus/gb.m3u8") == 1


def test_add_unknown_preset_rejected(client):
    r = client.post("/api/sources", json={"preset": "nope"})
    assert r.status_code == 400


def test_set_epg_urls_and_toggle_auto(client, app):
    resp = client.post(
        "/api/epg", json={"epg_urls": ["http://manual/g.xml"], "epg_auto": False}
    )
    assert resp.status_code == 200
    cfg = app.config["TUNAAR"]
    assert cfg.epg_urls == ["http://manual/g.xml"]
    assert cfg.epg_auto is False
