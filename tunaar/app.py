"""Tunaar Flask application.

Exposes the HDHomeRun emulation endpoints Plex needs, an XMLTV guide endpoint,
proxied/remuxed streaming with tuner-slot accounting, and a branded web
dashboard with a small JSON API.
"""

from __future__ import annotations

import threading
import time

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
)

from . import __version__, epg, m3u, proxy
from .config import Config


def _base_url(config: Config) -> str:
    if config.advertised_url:
        return config.advertised_url.rstrip("/")
    return request.host_url.rstrip("/")


class ChannelCache:
    """Thread-safe cache of the parsed playlist."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._channels: list[m3u.Channel] = []
        self._fetched_at = 0.0
        self._error: str | None = None

    def get(self) -> list[m3u.Channel]:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > self._config.playlist_refresh
            if self._channels and not stale:
                return self._channels
            try:
                self._channels = m3u.load(
                    self._config.playlist, user_agent=self._config.user_agent
                )
                self._fetched_at = time.monotonic()
                self._error = None
            except Exception as exc:  # noqa: BLE001 - surfaced on dashboard
                self._error = str(exc)
            return self._channels

    def by_number(self, number: str) -> m3u.Channel | None:
        return next((c for c in self.get() if c.number == number), None)

    @property
    def error(self) -> str | None:
        return self._error


class EpgCache:
    """Thread-safe cache of the (optionally filtered) XMLTV guide."""

    def __init__(self, config: Config, channels: ChannelCache) -> None:
        self._config = config
        self._channels = channels
        self._lock = threading.Lock()
        self._result: epg.EpgResult | None = None
        self._fetched_at = 0.0
        self._error: str | None = None
        self._matched = 0

    def get(self) -> epg.EpgResult:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > self._config.epg_refresh
            if self._result is not None and not stale:
                return self._result
            if not self._config.epg_url:
                self._result = epg.EpgResult(epg.EMPTY_XMLTV, set(), 0)
                return self._result
            try:
                raw = epg.fetch(self._config.epg_url, user_agent=self._config.user_agent)
                keep = None
                if self._config.filter_epg_to_lineup:
                    keep = {c.tvg_id for c in self._channels.get() if c.tvg_id}
                self._result = epg.build(raw, keep_ids=keep)
                lineup_ids = {c.tvg_id for c in self._channels.get() if c.tvg_id}
                self._matched = len(lineup_ids & self._result.channel_ids)
                self._fetched_at = time.monotonic()
                self._error = None
            except Exception as exc:  # noqa: BLE001 - surfaced on dashboard
                self._error = str(exc)
                if self._result is None:
                    self._result = epg.EpgResult(epg.EMPTY_XMLTV, set(), 0)
            return self._result

    @property
    def matched(self) -> int:
        return self._matched

    @property
    def error(self) -> str | None:
        return self._error


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.load()
    app = Flask(__name__)

    channels = ChannelCache(config)
    guide = EpgCache(config, channels)
    tuners = proxy.TunerManager(config.tuner_count)

    app.config.update(TUNAAR=config, CHANNELS=channels, EPG=guide, TUNERS=tuners)

    # -- HDHomeRun emulation ---------------------------------------------

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
                "DeviceAuth": "tunaar",
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
                for ch in channels.get()
            ]
        )

    @app.post("/lineup.post")
    def lineup_post() -> Response:
        return Response(status=200)

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

    # -- EPG --------------------------------------------------------------

    @app.get("/epg.xml")
    def epg_xml() -> Response:
        return Response(guide.get().xml, mimetype="application/xml")

    # -- Streaming --------------------------------------------------------

    @app.get("/stream/<number>")
    def stream(number: str):
        ch = channels.by_number(number)
        if ch is None:
            return Response("Unknown channel", status=404)

        if config.stream_mode == "redirect":
            return redirect(ch.url, code=302)

        try:
            session = tuners.acquire(ch.number, ch.name)
        except proxy.TunersBusy as exc:
            return Response(f"Tuner busy: {exc}", status=503)

        use_ffmpeg = config.stream_mode == "ffmpeg" and proxy.ffmpeg_available(
            config.ffmpeg_path
        )
        if use_ffmpeg:
            source = proxy.ffmpeg_stream(
                ch.url,
                ffmpeg_path=config.ffmpeg_path,
                user_agent=config.user_agent,
                chunk=config.buffer_chunk,
            )
        else:
            source = proxy.direct_stream(
                ch.url, user_agent=config.user_agent, chunk=config.buffer_chunk
            )

        def generate():
            try:
                yield from source
            finally:
                source.close()
                tuners.release(session)

        return Response(
            stream_with_context(generate()), mimetype="video/mp2t"
        )

    # -- Dashboard + API --------------------------------------------------

    @app.get("/")
    def dashboard() -> str:
        return render_template(
            "dashboard.html",
            name=config.friendly_name,
            version=__version__,
        )

    @app.get("/api/status")
    def api_status() -> Response:
        chans = channels.get()
        epg_result = guide.get()  # build before reading match stats
        return jsonify(
            {
                "name": config.friendly_name,
                "version": __version__,
                "device_id": config.device_id,
                "stream_mode": config.stream_mode,
                "ffmpeg": proxy.ffmpeg_available(config.ffmpeg_path),
                "channels": len(chans),
                "playlist_error": channels.error,
                "epg": {
                    "configured": bool(config.epg_url),
                    "matched": guide.matched,
                    "programmes": epg_result.programme_count,
                    "error": guide.error,
                },
                "tuners": {
                    "capacity": config.tuner_count,
                    "in_use": tuners.in_use,
                    "active": tuners.active(),
                },
            }
        )

    @app.get("/api/channels")
    def api_channels() -> Response:
        return jsonify(
            [
                {
                    "number": ch.number,
                    "name": ch.name,
                    "group": ch.group,
                    "logo": ch.logo,
                    "tvg_id": ch.tvg_id,
                }
                for ch in channels.get()
            ]
        )

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok", "version": __version__})

    return app
