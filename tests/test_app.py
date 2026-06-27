# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke tests for the Tunaar HTTP endpoints."""

import pytest

from tunaar import m3u
from tunaar.app import create_app
from tunaar.config import Config

SAMPLE = [
    m3u.Channel(number="1", name="News", url="http://example.com/news.m3u8", tvg_id="news.us"),
    m3u.Channel(number="7", name="Sports", url="http://example.com/sports.m3u8", tvg_id="sports.us"),
]


@pytest.fixture
def app(tmp_path):
    cfg = Config(
        friendly_name="TestTuner",
        device_id="DEADBEEF",
        tuner_count=2,
        playlist="dummy.m3u",
        stream_mode="redirect",  # avoid spawning ffmpeg / network in tests
        path=str(tmp_path / "config.json"),
    )
    application = create_app(cfg)
    # Pin the channel cache so no real playlist fetch happens.
    application.config["CHANNELS"]._channels = SAMPLE
    application.config["CHANNELS"]._fetched_at = float("inf")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_discover(client):
    data = client.get("/discover.json").get_json()
    assert data["FriendlyName"] == "TestTuner"
    assert data["DeviceID"] == "DEADBEEF"
    assert data["TunerCount"] == 2
    assert data["LineupURL"].endswith("/lineup.json")


def test_lineup(client):
    data = client.get("/lineup.json").get_json()
    assert len(data) == 2
    assert data[0]["GuideNumber"] == "1"
    assert data[0]["URL"].endswith("/stream/1")


def test_redirect_mode_does_not_consume_tuner(client, app):
    resp = client.get("/stream/7")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://example.com/sports.m3u8"
    assert app.config["TUNERS"].in_use == 0


def test_stream_unknown_channel(client):
    assert client.get("/stream/999").status_code == 404


def test_device_xml(client):
    resp = client.get("/device.xml")
    assert resp.status_code == 200
    assert "TestTuner" in resp.get_data(as_text=True)


def test_epg_empty_when_not_configured(client):
    resp = client.get("/epg.xml")
    assert resp.status_code == 200
    assert b"<tv" in resp.data


def test_api_status(client):
    s = client.get("/api/status").get_json()
    assert s["name"] == "TestTuner"
    assert s["channels"] == 2
    assert s["tuners"]["capacity"] == 2
    assert s["tuners"]["in_use"] == 0


def test_api_channels(client):
    rows = client.get("/api/channels").get_json()
    assert {r["number"] for r in rows} == {"1", "7"}


def test_healthz(client):
    assert client.get("/healthz").get_json()["status"] == "ok"


def test_pwa_manifest_and_sw(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200
    data = m.get_json()
    assert data["display"] == "standalone" and data["start_url"] == "/"
    assert data["icons"]
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "application/javascript" in sw.headers["Content-Type"]
    assert sw.headers.get("Service-Worker-Allowed") == "/"
    assert b"addEventListener('fetch'" in sw.get_data()


def test_security_headers(client):
    h = client.get("/healthz").headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "SAMEORIGIN"
    assert h.get("Referrer-Policy") == "no-referrer"


def test_rate_limiter_unit():
    from tunaar.app import RateLimiter
    rl = RateLimiter(limit=2, window=10.0)
    assert rl.allow("ip", now=0.0) is True
    assert rl.allow("ip", now=1.0) is True
    assert rl.allow("ip", now=2.0) is False       # 3rd in window → blocked
    assert rl.allow("ip", now=12.0) is True        # window rolled over
    assert rl.allow("other", now=2.0) is True      # separate key unaffected


def test_readyz(client):
    # Channels are pinned in the fixture, so the app reports ready.
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ready" and body["channels"] == 2


def test_dashboard_renders(client):
    html = client.get("/").get_data(as_text=True)
    assert "TestTuner" in html
