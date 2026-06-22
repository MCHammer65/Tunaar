"""Smoke tests for the HDHomeRun emulation endpoints."""

import pytest

from plexiptv import m3u
from plexiptv.app import ChannelCache, create_app
from plexiptv.config import Config

SAMPLE = [
    m3u.Channel(number="1", name="News", url="http://example.com/news.m3u8"),
    m3u.Channel(number="7", name="Sports", url="http://example.com/sports.m3u8"),
]


@pytest.fixture
def client(monkeypatch):
    config = Config(
        friendly_name="TestTuner",
        device_id="DEADBEEF",
        tuner_count=2,
        host="127.0.0.1",
        port=5004,
        playlist="dummy.m3u",
        advertised_url=None,
    )
    app = create_app(config)
    # Replace the cache so no real playlist fetch happens.
    cache = ChannelCache("dummy.m3u")
    cache._channels = SAMPLE
    cache._fetched_at = float("inf")
    app.config["CHANNELS"] = cache
    monkeypatch.setattr("plexiptv.app.ChannelCache.get", lambda self: SAMPLE)
    monkeypatch.setattr(
        "plexiptv.app.ChannelCache.by_number",
        lambda self, n: next((c for c in SAMPLE if c.number == n), None),
    )
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
    assert data[0]["GuideName"] == "News"
    assert data[0]["URL"].endswith("/stream/1")


def test_lineup_status(client):
    data = client.get("/lineup_status.json").get_json()
    assert data["ScanInProgress"] == 0


def test_stream_redirects(client):
    resp = client.get("/stream/7")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://example.com/sports.m3u8"


def test_stream_unknown_channel(client):
    assert client.get("/stream/999").status_code == 404


def test_device_xml(client):
    resp = client.get("/device.xml")
    assert resp.status_code == 200
    assert "TestTuner" in resp.get_data(as_text=True)
