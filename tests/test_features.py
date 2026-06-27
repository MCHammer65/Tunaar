# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
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


def test_one_bad_epg_url_does_not_wipe_guide(tmp_path, monkeypatch):
    playlist = '#EXTM3U\n#EXTINF:-1 tvg-id="cnn.x",CNN\nhttp://x/cnn\n'
    good = (
        b'<?xml version="1.0"?><tv>'
        b'<channel id="cnn.x"><display-name>CNN</display-name></channel>'
        b'<programme start="20260101060000 +0000" channel="cnn.x"><title>News</title></programme>'
        b'</tv>'
    )

    def fake_fetch(url, **k):
        if "bad" in url:
            raise RuntimeError("404 Not Found")
        return good

    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: playlist)
    monkeypatch.setattr("tunaar.epg.fetch", fake_fetch)

    cfg = Config(
        device_id="EPGOK",
        sources=[{"name": "S", "url": "http://x/l.m3u"}],
        epg_urls=["http://good/guide.xml", "http://bad/guide.xml"],
        epg_auto=False,
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()

    status = client.get("/api/status").get_json()
    # The good source still produced a guide despite the bad one 404ing.
    assert status["epg"]["programmes"] == 1
    assert status["epg"]["matched"] == 1
    # ...and the failure is surfaced, not silently swallowed.
    assert "unreachable" in (status["epg"].get("error") or "")


def test_epg_urls_split_when_pasted_on_one_line(client, app):
    # Two URLs pasted on a single line (space-separated) must become two URLs,
    # not one broken concatenation.
    one_line = "http://a/guide.xml http://b/guide.xml,http://a/guide.xml"
    r = client.post("/api/epg", json={"epg_urls": [one_line], "epg_auto": False})
    assert r.status_code == 200
    assert app.config["TUNAAR"].epg_urls == ["http://a/guide.xml", "http://b/guide.xml"]


def test_status_reports_failed_sources(tmp_path, monkeypatch):
    good = "#EXTM3U\n#EXTINF:-1,Good\nhttp://x/good\n"

    def fake_fetch(url, **k):
        if "bad" in url:
            raise RuntimeError("404")
        return good

    monkeypatch.setattr(m3u, "_fetch_text", fake_fetch)
    cfg = Config(
        device_id="FAIL1",
        sources=[{"url": "http://ok/l.m3u"}, {"url": "http://bad/l.m3u"}],
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()
    status = client.get("/api/status").get_json()
    assert status["playlist_failed"] == ["http://bad/l.m3u"]
    assert status["channels"] == 1  # good source still loaded


def test_manual_epg_mapping_overrides_match(tmp_path, monkeypatch):
    # An OTA-style channel with no tvg-id and a name the guide won't match.
    playlist = '#EXTM3U\n#EXTINF:-1,BBC One South\nhttp://x/bbc\n'
    epg_xml = (
        b'<?xml version="1.0"?><tv>'
        b'<channel id="bbc1.uk"><display-name>BBC One</display-name></channel>'
        b'<programme start="20260101060000 +0000" channel="bbc1.uk"><title>News</title></programme>'
        b'</tv>'
    )
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: playlist)
    monkeypatch.setattr("tunaar.epg.fetch", lambda url, **k: epg_xml)

    cfg = Config(
        device_id="MAP1",
        sources=[{"name": "OTA", "url": "http://x/l.m3u"}],
        epg_urls=["http://x/guide.xml"],
        epg_auto=False,
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()

    # "BBC One South" does not auto-match "BBC One".
    assert client.get("/api/status").get_json()["epg"]["matched"] == 0
    # The guide channel is offered for mapping.
    guide_chans = client.get("/api/epg/guide-channels").get_json()
    assert {"id": "bbc1.uk", "name": "BBC One"} in guide_chans
    # Map it manually, and now it matches.
    r = client.post("/api/epg/map", json={"name": "BBC One South", "tvg_id": "bbc1.uk"})
    assert r.status_code == 200
    assert client.get("/api/status").get_json()["epg"]["matched"] == 1
    assert client.get("/api/channels").get_json()[0]["tvg_id"] == "bbc1.uk"
    # Clearing the mapping reverts it.
    client.post("/api/epg/map", json={"name": "BBC One South", "tvg_id": ""})
    assert client.get("/api/status").get_json()["epg"]["matched"] == 0


def test_epg_map_requires_name(client):
    assert client.post("/api/epg/map", json={"tvg_id": "x"}).status_code == 400


def test_align_ids_guarantees_match(tmp_path, monkeypatch):
    # Channel carries a tvg-id that matches the guide, but we want the served
    # guide re-keyed to the lineup number so any player attaches it.
    playlist = '#EXTM3U\n#EXTINF:-1 tvg-id="bbc1.uk",BBC One\nhttp://x/bbc\n'
    epg_xml = (
        b'<?xml version="1.0"?><tv>'
        b'<channel id="bbc1.uk"><display-name>BBC One</display-name></channel>'
        b'<programme start="20260101060000 +0000" channel="bbc1.uk"><title>News</title></programme>'
        b'</tv>'
    )
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: playlist)
    monkeypatch.setattr("tunaar.epg.fetch", lambda url, **k: epg_xml)

    cfg = Config(
        device_id="ALN1",
        sources=[{"name": "IPTV", "url": "http://x/l.m3u"}],
        epg_urls=["http://x/guide.xml"],
        epg_auto=False,
        epg_align_ids=True,
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()

    number = client.get("/api/channels").get_json()[0]["number"]
    served = client.get("/epg.xml").get_data()
    # The served guide is keyed on the lineup number, not the original tvg-id.
    assert f'<channel id="{number}"'.encode() in served
    assert b'id="bbc1.uk"' not in served
    assert f'channel="{number}"'.encode() in served
    assert client.get("/api/status").get_json()["epg"]["matched"] == 1


def test_align_ids_toggle_persists(client):
    r = client.post("/api/epg", json={"epg_align_ids": True})
    assert r.status_code == 200 and r.get_json()["epg_align_ids"] is True
    assert client.get("/api/config").get_json()["epg_align_ids"] is True


def test_setup_complete_flag(client, app):
    # Fresh config defaults to not-complete so the wizard auto-opens.
    assert client.get("/api/config").get_json()["setup_complete"] is False
    r = client.post("/api/setup/complete", json={"complete": True})
    assert r.status_code == 200
    assert client.get("/api/config").get_json()["setup_complete"] is True
    assert app.config["TUNAAR"].setup_complete is True
    # Can be reset (e.g. to re-run the wizard).
    client.post("/api/setup/complete", json={"complete": False})
    assert client.get("/api/config").get_json()["setup_complete"] is False


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
    assert {"uk", "us", "ca", "fr", "jm"} <= ids
    assert all(p["added"] is False for p in presets)  # none added yet
    assert {"GB", "US", "CA", "FR", "JM"} <= {p["region"] for p in presets}


def test_add_preset_toggles_source(client):
    r = client.post("/api/sources", json={"preset": "uk"})
    assert r.get_json()["added"] is True
    sources = r.get_json()["sources"]
    assert sources[-1]["url"] == "https://iptv-org.github.io/iptv/countries/uk.m3u"
    assert sources[-1]["group"] == "United Kingdom"
    presets = {p["id"]: p for p in client.get("/api/presets").get_json()}
    assert presets["uk"]["added"] is True
    # Clicking the same preset again removes it (toggle).
    r2 = client.post("/api/sources", json={"preset": "uk"})
    assert r2.get_json()["added"] is False
    urls = [s["url"] for s in client.get("/api/config").get_json()["sources"]]
    assert "https://iptv-org.github.io/iptv/countries/uk.m3u" not in urls


def test_add_unknown_preset_rejected(client):
    r = client.post("/api/sources", json={"preset": "nope"})
    assert r.status_code == 400


def test_add_xtream_source_auto_derives_epg(client, app):
    url = "http://host:8080/get.php?username=u&password=p&type=m3u_plus"
    r = client.post("/api/sources", json={"url": url}).get_json()
    assert r["derived_epg"] == "http://host:8080/xmltv.php?username=u&password=p"
    assert "http://host:8080/xmltv.php?username=u&password=p" in app.config["TUNAAR"].epg_urls


def test_add_source_with_limit_persists(client, app):
    client.post("/api/sources", json={"url": "http://x/2.m3u", "limit": 50})
    assert app.config["TUNAAR"].sources[-1]["limit"] == 50


def test_epg_presets_listed_and_added(client, app):
    presets = client.get("/api/epg-presets").get_json()
    ids = {p["id"] for p in presets}
    assert "epg-uk" in ids
    assert all(p["added"] is False for p in presets)
    r = client.post("/api/epg/preset", json={"id": "epg-uk"})
    assert r.status_code == 200 and r.get_json()["added"] is True
    assert any("UK1" in u for u in app.config["TUNAAR"].epg_urls)
    # Clicking again toggles it back off.
    r2 = client.post("/api/epg/preset", json={"id": "epg-uk"})
    assert r2.get_json()["added"] is False
    assert not any("UK1" in u for u in app.config["TUNAAR"].epg_urls)
    assert {p["id"]: p["added"] for p in client.get("/api/epg-presets").get_json()}["epg-uk"] is False


def test_epg_preset_unknown_rejected(client):
    assert client.post("/api/epg/preset", json={"id": "nope"}).status_code == 400


def test_license_nag_default_blocks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    # Default enforcement is "nag": expired trial still allows everything.
    cfg = Config(
        device_id="LIC0",
        sources=[{"name": "M", "url": "http://x/l.m3u"}],
        trial_start=1.0,  # trial long expired
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()
    status = client.get("/api/status").get_json()["license"]
    assert status["state"] == "expired" and status["enforce"] == "nag"
    assert client.post("/api/epg/preset", json={"id": "epg-uk"}).status_code == 200
    assert client.post("/api/epg/map", json={"name": "CNN", "tvg_id": "x"}).status_code == 200
    assert client.post("/api/test/all").status_code == 200


def test_buy_url_exposed_in_status(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    cfg = Config(
        device_id="BUY1",
        sources=[{"name": "M", "url": "http://x/l.m3u"}],
        buy_url="https://store.example.com/checkout",
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()
    assert client.get("/api/status").get_json()["license"]["buy_url"] == "https://store.example.com/checkout"


def test_license_premium_mode_gates_extras(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    cfg = Config(
        device_id="LIC1",
        sources=[{"name": "M", "url": "http://x/l.m3u"}],
        trial_start=1.0,
        license_enforce="premium",  # opt into gating
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    client = create_app(cfg).test_client()
    assert client.get("/api/status").get_json()["license"]["state"] == "expired"
    # Premium extras → 402.
    assert client.post("/api/sources", json={"preset": "uk"}).status_code == 402
    assert client.post("/api/sources", json={"url": "http://h", "type": "hdhr"}).status_code == 402
    assert client.post("/api/epg/preset", json={"id": "epg-uk"}).status_code == 402
    assert client.post("/api/epg/map", json={"name": "CNN", "tvg_id": "x"}).status_code == 402
    assert client.post("/api/test/all").status_code == 402
    # Core stays free even in premium mode.
    assert client.post("/api/sources", json={"url": "http://x/2.m3u"}).status_code == 200
    assert client.post("/api/groups", json={"exclude": ["News"]}).status_code == 200


def test_license_active_trial_allows_premium(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    cfg = Config(
        device_id="LIC2", sources=[], stream_mode="redirect",
        path=str(tmp_path / "config.json"),  # trial_start seeded to now on load
    )
    client = create_app(cfg).test_client()
    assert client.get("/api/status").get_json()["license"]["state"] == "trial"
    assert client.post("/api/epg/preset", json={"id": "epg-uk"}).status_code == 200


def test_invalid_license_key_rejected(client, monkeypatch):
    # Reachable but Lemon Squeezy rejects the key (e.g. activation limit) → 400.
    monkeypatch.setattr("tunaar.license.activate_ls", lambda key, name, **k: {
        "reachable": True, "valid": False,
        "error": "This license key has reached the activation limit.",
    })
    r = client.post("/api/license", json={"key": "not-a-key"})
    assert r.status_code == 400
    assert "activation limit" in r.get_json()["message"]


def test_valid_license_key_activates(client, app, monkeypatch):
    monkeypatch.setattr("tunaar.license.activate_ls", lambda key, name, **k: {
        "reachable": True, "valid": True, "plan": "lifetime",
        "email": "buyer@example.com", "expires_at": None, "instance_id": "inst-123",
    })
    r = client.post("/api/license", json={"key": "VALID-KEY"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["state"] == "licensed" and body["plan"] == "lifetime"
    assert app.config["TUNAAR"].license_key == "VALID-KEY"
    assert app.config["TUNAAR"].license_instance_id == "inst-123"


def test_license_key_unreachable_returns_503(client, monkeypatch):
    monkeypatch.setattr("tunaar.license.activate_ls", lambda key, name, **k: {"reachable": False})
    assert client.post("/api/license", json={"key": "x"}).status_code == 503


def test_bulk_stream_health_check(client, monkeypatch):
    # CNN ok, ESPN dead, Orphan ok (per probe stub keyed on URL).
    def fake_probe(url, **k):
        return {"ok": "espn" not in url, "status": 200 if "espn" not in url else 502}
    monkeypatch.setattr("tunaar.proxy.probe", fake_probe)
    r = client.post("/api/test/all").get_json()
    assert r["tested"] == 3
    assert r["ok"] == 2
    assert [f["name"] for f in r["failed"]] == ["ESPN"]


def test_about_page(client):
    r = client.get("/about")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Muneris Management Ltd" in body
    assert "AGPL" in body
    assert "info@muneris.co.uk" in body


def test_docs_served_and_traversal_blocked(client):
    assert client.get("/docs/user-guide.html").status_code == 200
    assert client.get("/docs/install.html").status_code == 200
    assert client.get("/docs/").status_code == 200
    assert client.get("/docs/../app.py").status_code == 404
    assert client.get("/docs/missing.html").status_code == 404


def test_set_epg_urls_and_toggle_auto(client, app):
    resp = client.post(
        "/api/epg", json={"epg_urls": ["http://manual/g.xml"], "epg_auto": False}
    )
    assert resp.status_code == 200
    cfg = app.config["TUNAAR"]
    assert cfg.epg_urls == ["http://manual/g.xml"]
    assert cfg.epg_auto is False
