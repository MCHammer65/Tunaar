"""Tunaar Flask application.

Exposes the HDHomeRun emulation endpoints Plex needs, an XMLTV guide endpoint,
proxied/remuxed streaming with tuner-slot accounting, and a branded web
dashboard with a small JSON API.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import sys
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
from .logbus import BusHandler, LogBus

log = logging.getLogger("tunaar")


def _base_url(config: Config) -> str:
    if config.advertised_url:
        return config.advertised_url.rstrip("/")
    return request.host_url.rstrip("/")


class ChannelCache:
    """Thread-safe cache of the merged, group-filtered playlist."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._channels: list[m3u.Channel] = []
        self._all_groups: list[str] = []
        self._discovered_epg: list[str] = []
        self._fetched_at = 0.0
        self._error: str | None = None

    def _passes_group_filter(self, group: str) -> bool:
        inc = self._config.groups_include
        exc = self._config.groups_exclude
        if inc and group not in inc:
            return False
        if group in exc:
            return False
        return True

    def get(self) -> list[m3u.Channel]:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > self._config.playlist_refresh
            if self._channels and not stale:
                return self._channels
            try:
                playlist = m3u.load_sources(
                    self._config.sources, user_agent=self._config.user_agent
                )
                self._all_groups = sorted({c.group for c in playlist.channels})
                self._discovered_epg = playlist.epg_urls
                kept = [
                    c for c in playlist.channels if self._passes_group_filter(c.group)
                ]
                m3u.assign_numbers(kept)
                self._channels = kept
                self._fetched_at = time.monotonic()
                self._error = None
                log.info(
                    "Playlist loaded: %d channels from %d source(s)",
                    len(kept), len(self._config.sources),
                )
            except Exception as exc:  # noqa: BLE001 - surfaced on dashboard
                self._error = str(exc)
                log.error("Playlist load failed: %s", exc)
            return self._channels

    def by_number(self, number: str) -> m3u.Channel | None:
        return next((c for c in self.get() if c.number == number), None)

    def invalidate(self) -> None:
        with self._lock:
            self._fetched_at = 0.0

    @property
    def all_groups(self) -> list[str]:
        self.get()
        return self._all_groups

    @property
    def discovered_epg(self) -> list[str]:
        self.get()
        return self._discovered_epg

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
        self._sources_used = 0

    def get(self) -> epg.EpgResult:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > self._config.epg_refresh
            if self._result is not None and not stale:
                return self._result

            urls = self._config.effective_epg_urls(self._channels.discovered_epg)
            self._sources_used = len(urls)
            if not urls:
                self._result = epg.EpgResult(epg.EMPTY_XMLTV, set(), 0)
                self._matched = 0
                self._fetched_at = time.monotonic()
                return self._result
            try:
                raw_docs = []
                for url in urls:
                    raw_docs.append(
                        epg.fetch(url, user_agent=self._config.user_agent)
                    )
                lineup_ids = {c.tvg_id for c in self._channels.get() if c.tvg_id}
                keep = lineup_ids if self._config.filter_epg_to_lineup else None
                self._result = epg.build_many(raw_docs, keep_ids=keep)
                self._matched = len(lineup_ids & self._result.channel_ids)
                self._fetched_at = time.monotonic()
                self._error = None
                log.info(
                    "EPG loaded: %d source(s), %d programmes, %d channels matched",
                    len(urls), self._result.programme_count, self._matched,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced on dashboard
                self._error = str(exc)
                log.error("EPG load failed: %s", exc)
                if self._result is None:
                    self._result = epg.EpgResult(epg.EMPTY_XMLTV, set(), 0)
            return self._result

    def invalidate(self) -> None:
        with self._lock:
            self._fetched_at = 0.0

    @property
    def matched(self) -> int:
        return self._matched

    @property
    def sources_used(self) -> int:
        return getattr(self, "_sources_used", 0)

    @property
    def error(self) -> str | None:
        return self._error


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.load()
    app = Flask(__name__)

    channels = ChannelCache(config)
    guide = EpgCache(config, channels)
    tuners = proxy.TunerManager(config.tuner_count)

    bus = LogBus()
    started_at = time.time()
    # Bind this app's bus as the active log sink (one app per process in prod;
    # tests create several, so always rebind to the latest).
    for h in list(log.handlers):
        if isinstance(h, BusHandler):
            log.removeHandler(h)
    log.addHandler(BusHandler(bus))
    log.setLevel(logging.INFO)

    app.config.update(
        TUNAAR=config, CHANNELS=channels, EPG=guide, TUNERS=tuners, LOGBUS=bus
    )

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
            log.warning("Tuner busy — refused %s (%s): %s", ch.number, ch.name, exc)
            return Response(f"Tuner busy: {exc}", status=503)

        use_ffmpeg = config.stream_mode == "ffmpeg" and proxy.ffmpeg_available(
            config.ffmpeg_path
        )
        log.info(
            "Stream start ch %s '%s' [%s] for %s",
            ch.number, ch.name, "ffmpeg" if use_ffmpeg else "direct",
            request.remote_addr or "?",
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
                log.info("Stream end ch %s '%s'", ch.number, ch.name)

        return Response(
            stream_with_context(generate()), mimetype="video/mp2t"
        )

    # -- Console ----------------------------------------------------------

    @app.get("/console")
    def console() -> str:
        return render_template(
            "console.html", name=config.friendly_name, version=__version__
        )

    @app.get("/api/system")
    def api_system() -> Response:
        return jsonify(
            {
                "name": config.friendly_name,
                "version": __version__,
                "device_id": config.device_id,
                "uptime": round(time.time() - started_at),
                "python": platform.python_version(),
                "stream_mode": config.stream_mode,
                "ffmpeg": proxy.ffmpeg_available(config.ffmpeg_path),
                "discovery": config.discovery,
                "tuners": {
                    "capacity": config.tuner_count,
                    "in_use": tuners.in_use,
                    "active": tuners.active(),
                },
            }
        )

    @app.get("/api/logs")
    def api_logs() -> Response:
        limit = request.args.get("limit", default=200, type=int)
        return jsonify(bus.recent(limit))

    @app.get("/api/logs/stream")
    def api_logs_stream() -> Response:
        def gen():
            q = bus.subscribe()
            try:
                yield "retry: 3000\n\n"
                while True:
                    try:
                        rec = q.get(timeout=15)
                        yield f"data: {json.dumps(rec)}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"  # heartbeat
            finally:
                bus.unsubscribe(q)

        return Response(
            stream_with_context(gen()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/test/<number>")
    def api_test(number: str) -> Response:
        ch = channels.by_number(number)
        if ch is None:
            return jsonify({"error": "unknown channel"}), 404
        log.info("Testing channel %s '%s'", ch.number, ch.name)
        result = proxy.probe(ch.url, user_agent=config.user_agent)
        result["channel"] = ch.number
        result["name"] = ch.name
        level = "info" if result.get("ok") else "warning"
        getattr(log, level)(
            "Test %s '%s': %s", ch.number, ch.name,
            "OK" if result.get("ok") else result.get("error", "failed"),
        )
        return jsonify(result)

    @app.post("/api/restart")
    def api_restart() -> Response:
        log.warning("Restart requested via console")

        def _exit():
            time.sleep(0.5)
            os._exit(0)  # container restart policy brings us back

        threading.Thread(target=_exit, daemon=True).start()
        return jsonify({"ok": True, "message": "restarting"})

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
                    "configured": guide.sources_used > 0,
                    "sources": guide.sources_used,
                    "auto": config.epg_auto,
                    "matched": guide.matched,
                    "programmes": epg_result.programme_count,
                    "error": guide.error,
                },
                "groups": len(channels.all_groups),
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
                    "source": ch.source,
                }
                for ch in channels.get()
            ]
        )

    # -- Management API ---------------------------------------------------

    def _refresh() -> None:
        channels.invalidate()
        guide.invalidate()

    def _save_and_refresh() -> None:
        try:
            config.save()
        except OSError:
            pass  # read-only config dir: changes still apply for this run
        _refresh()

    @app.get("/api/config")
    def api_config() -> Response:
        return jsonify(
            {
                "sources": config.sources,
                "epg_urls": config.epg_urls,
                "epg_auto": config.epg_auto,
                "discovered_epg": channels.discovered_epg,
                "groups_include": config.groups_include,
                "groups_exclude": config.groups_exclude,
                "all_groups": channels.all_groups,
            }
        )

    @app.post("/api/sources")
    def api_add_source() -> Response:
        body = request.get_json(silent=True) or {}
        url = (body.get("url") or "").strip()
        if not url:
            return jsonify({"error": "url is required"}), 400
        config.sources.append(
            {
                "name": (body.get("name") or "").strip(),
                "url": url,
                "group": (body.get("group") or "").strip(),
            }
        )
        _save_and_refresh()
        return jsonify({"ok": True, "sources": config.sources})

    @app.delete("/api/sources/<int:index>")
    def api_remove_source(index: int) -> Response:
        if 0 <= index < len(config.sources):
            config.sources.pop(index)
            _save_and_refresh()
            return jsonify({"ok": True, "sources": config.sources})
        return jsonify({"error": "index out of range"}), 404

    @app.post("/api/epg")
    def api_set_epg() -> Response:
        body = request.get_json(silent=True) or {}
        if "epg_auto" in body:
            config.epg_auto = bool(body["epg_auto"])
        if "epg_urls" in body and isinstance(body["epg_urls"], list):
            config.epg_urls = [str(u).strip() for u in body["epg_urls"] if str(u).strip()]
        _save_and_refresh()
        return jsonify(
            {"ok": True, "epg_urls": config.epg_urls, "epg_auto": config.epg_auto}
        )

    @app.post("/api/groups")
    def api_set_groups() -> Response:
        body = request.get_json(silent=True) or {}
        if "include" in body and isinstance(body["include"], list):
            config.groups_include = [str(g) for g in body["include"]]
        if "exclude" in body and isinstance(body["exclude"], list):
            config.groups_exclude = [str(g) for g in body["exclude"]]
        _save_and_refresh()
        return jsonify(
            {
                "ok": True,
                "groups_include": config.groups_include,
                "groups_exclude": config.groups_exclude,
            }
        )

    @app.post("/api/refresh")
    def api_refresh() -> Response:
        _refresh()
        return jsonify({"ok": True})

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok", "version": __version__})

    return app
