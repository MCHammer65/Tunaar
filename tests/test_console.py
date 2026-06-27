# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the admin console: log bus and console API."""

import pytest

from tunaar import m3u, proxy
from tunaar.app import create_app
from tunaar.config import Config
from tunaar.logbus import LogBus

PLAYLIST = "#EXTM3U\n#EXTINF:-1,Test One\nhttp://x/one\n"


def test_logbus_recent_and_capacity():
    bus = LogBus(capacity=3)
    for i in range(5):
        bus.publish("INFO", f"msg {i}")
    recent = bus.recent()
    assert [r["msg"] for r in recent] == ["msg 2", "msg 3", "msg 4"]
    assert all("id" in r and "t" in r for r in recent)


def test_logbus_subscribe_receives_new():
    bus = LogBus()
    q = bus.subscribe()
    bus.publish("WARNING", "hello")
    rec = q.get(timeout=1)
    assert rec["msg"] == "hello"
    assert rec["level"] == "WARNING"
    bus.unsubscribe(q)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(m3u, "_fetch_text", lambda src, **k: PLAYLIST)
    cfg = Config(
        device_id="CONSOLE1",
        sources=[{"name": "Main", "url": "http://x/list.m3u"}],
        stream_mode="redirect",
        path=str(tmp_path / "config.json"),
    )
    return create_app(cfg)


@pytest.fixture
def client(app):
    return app.test_client()


def test_console_page_renders(client):
    html = client.get("/console").get_data(as_text=True)
    assert "Live activity" in html


def test_api_system(client):
    s = client.get("/api/system").get_json()
    assert s["device_id"] == "CONSOLE1"
    assert "uptime" in s and "python" in s
    assert s["tuners"]["capacity"] >= 1


def test_api_logs_records_activity(client):
    client.get("/api/channels")  # triggers a "Playlist loaded" log line
    logs = client.get("/api/logs").get_json()
    assert any("Playlist loaded" in r["msg"] for r in logs)


def test_api_test_channel(client, monkeypatch):
    monkeypatch.setattr(
        proxy, "probe",
        lambda url, **k: {"ok": True, "status": 200, "bytes": 8192, "ms": 12, "content_type": "video/mp2t"},
    )
    r = client.post("/api/test/1").get_json()
    assert r["ok"] is True
    assert r["channel"] == "1"
    assert r["name"] == "Test One"


def test_api_test_unknown_channel(client):
    assert client.post("/api/test/999").status_code == 404
