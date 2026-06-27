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


def test_dashboard_renders(client):
    html = client.get("/").get_data(as_text=True)
    assert "TestTuner" in html
