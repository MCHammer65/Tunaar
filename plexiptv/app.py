"""Flask application emulating an HDHomeRun tuner for Plex Live TV & DVR.

Plex discovers an HDHomeRun device by querying a small set of HTTP
endpoints. This app implements those endpoints, backed by an IPTV M3U
playlist:

    GET  /discover.json       device description Plex uses to identify the tuner
    GET  /lineup_status.json  scan/lineup status
    GET  /lineup.json         the channel lineup
    POST /lineup.post         channel-scan trigger (no-op, returns OK)
    GET  /device.xml          UPnP description (used by some discovery paths)
    GET  /stream/<number>     redirect to the real stream for a channel

To add the tuner in Plex: Settings -> Live TV & DVR -> "Set up Plex DVR"
and enter this server's address manually if it is not auto-detected.
"""

from __future__ import annotations

import time

from flask import Flask, Response, jsonify, redirect, request

from . import m3u
from .config import Config


def _base_url(config: Config) -> str:
    """The URL Plex should use to reach this server.

    Prefers an explicitly advertised URL; otherwise derives it from the
    incoming request so it works behind whatever address Plex used.
    """
    if config.advertised_url:
        return config.advertised_url.rstrip("/")
    return request.host_url.rstrip("/")


class ChannelCache:
    """Caches the parsed playlist so every request doesn't refetch it."""

    def __init__(self, source: str, ttl: int = 300) -> None:
        self.source = source
        self.ttl = ttl
        self._channels: list[m3u.Channel] = []
        self._fetched_at = 0.0

    def get(self) -> list[m3u.Channel]:
        if not self._channels or (time.monotonic() - self._fetched_at) > self.ttl:
            self._channels = m3u.load(self.source)
            self._fetched_at = time.monotonic()
        return self._channels

    def by_number(self, number: str) -> m3u.Channel | None:
        for ch in self.get():
            if ch.number == number:
                return ch
        return None


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.load()
    app = Flask(__name__)
    cache = ChannelCache(config.playlist)
    app.config["PLEXIPTV"] = config
    app.config["CHANNELS"] = cache

    @app.get("/")
    def index() -> Response:
        return jsonify(
            {
                "name": config.friendly_name,
                "channels": len(cache.get()),
                "endpoints": [
                    "/discover.json",
                    "/lineup_status.json",
                    "/lineup.json",
                    "/device.xml",
                ],
            }
        )

    @app.get("/discover.json")
    def discover() -> Response:
        base = _base_url(config)
        return jsonify(
            {
                "FriendlyName": config.friendly_name,
                "Manufacturer": "Silicondust",
                "ModelNumber": "HDTC-2US",
                "FirmwareName": "hdhomeruntc_atsc",
                "FirmwareVersion": "20170930",
                "DeviceID": config.device_id,
                "DeviceAuth": "plexiptv",
                "TunerCount": config.tuner_count,
                "BaseURL": base,
                "LineupURL": f"{base}/lineup.json",
            }
        )

    @app.get("/lineup_status.json")
    def lineup_status() -> Response:
        return jsonify(
            {
                "ScanInProgress": 0,
                "ScanPossible": 1,
                "Source": "Cable",
                "SourceList": ["Cable"],
            }
        )

    @app.get("/lineup.json")
    def lineup() -> Response:
        base = _base_url(config)
        return jsonify(
            [
                {
                    "GuideNumber": ch.number,
                    "GuideName": ch.name,
                    "URL": f"{base}/stream/{ch.number}",
                }
                for ch in cache.get()
            ]
        )

    @app.post("/lineup.post")
    def lineup_post() -> Response:
        # Plex may POST here to trigger a scan; nothing to do for IPTV.
        return Response(status=200)

    @app.get("/stream/<number>")
    def stream(number: str) -> Response:
        ch = cache.by_number(number)
        if ch is None:
            return Response("Unknown channel", status=404)
        return redirect(ch.url, code=302)

    @app.get("/device.xml")
    def device_xml() -> Response:
        base = _base_url(config)
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <URLBase>{base}</URLBase>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{config.friendly_name}</friendlyName>
    <manufacturer>Silicondust</manufacturer>
    <modelName>HDTC-2US</modelName>
    <modelNumber>HDTC-2US</modelNumber>
    <serialNumber>{config.device_id}</serialNumber>
    <UDN>uuid:{config.device_id}</UDN>
  </device>
</root>
"""
        return Response(xml, mimetype="application/xml")

    return app
