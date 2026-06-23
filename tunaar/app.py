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
import re
import sys
import threading
import time

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
)

from . import __version__, epg, m3u, presets, proxy
from .config import Config
from .logbus import BusHandler, LogBus

log = logging.getLogger("tunaar")

# The branded HTML guides live in <repo>/docs (one level above the package),
# and are also served by the dashboard so they're available offline.
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")


def _serve_doc(filename: str) -> Response:
    full = os.path.normpath(os.path.join(DOCS_DIR, filename))
    if not full.startswith(os.path.normpath(DOCS_DIR)) or not os.path.isfile(full):
        abort(404)
    return send_from_directory(DOCS_DIR, filename)


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
        # -inf guarantees staleness regardless of process uptime (monotonic()
        # is small early on, so 0.0 wouldn't reliably force a reload).
        with self._lock:
            self._fetched_at = float("-inf")

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
        self._guide_index: dict = {}  # all guide channels: tvg_id -> display name

    @property
    def guide_channels(self) -> list[dict]:
        """All channels present in the loaded guide, for the mapping UI."""
        return [
            {"id": cid, "name": name}
            for cid, name in sorted(self._guide_index.items(), key=lambda kv: kv[1].lower())
        ]

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
                # Fetch each source independently — one bad/404 URL must not
                # wipe out the whole guide, just get skipped with a warning.
                raw_docs = []
                failed: list[str] = []
                for url in urls:
                    try:
                        # Use epg.fetch's browser-like default UA — public EPG
                        # hosts often 404 the stream UA.
                        raw_docs.append(epg.fetch(url))
                    except Exception as exc:  # noqa: BLE001 - per-source, non-fatal
                        failed.append(url)
                        log.warning("EPG source failed, skipping: %s (%s)", url, exc)
                # Build the full guide first so we can name-match channels that
                # have no tvg-id (e.g. real HDHomeRun / OTA channels).
                full = epg.build_many(raw_docs, keep_ids=None)
                self._guide_index = dict(full.id_to_name)
                chans = self._channels.get()
                overrides = self._config.epg_overrides or {}
                matched_by_name = 0
                for ch in chans:
                    # A manual mapping always wins over auto name-matching.
                    if ch.name in overrides and overrides[ch.name]:
                        ch.tvg_id = overrides[ch.name]
                        continue
                    if not ch.tvg_id and full.name_to_id:
                        cid = full.name_to_id.get(epg.norm_name(ch.name))
                        if cid:
                            ch.tvg_id = cid
                            matched_by_name += 1

                lineup_ids = {c.tvg_id for c in chans if c.tvg_id}
                if self._config.filter_epg_to_lineup:
                    self._result = epg.build(full.xml, keep_ids=lineup_ids)
                else:
                    self._result = full
                self._matched = len(lineup_ids & full.channel_ids)
                self._fetched_at = time.monotonic()
                # Surface skipped sources without failing the whole guide.
                if failed:
                    self._error = (
                        f"{len(failed)} of {len(urls)} EPG source(s) unreachable: "
                        + ", ".join(failed)
                    )
                else:
                    self._error = None
                log.info(
                    "EPG loaded: %d/%d source(s), %d programmes, %d matched (%d by name)",
                    len(urls) - len(failed), len(urls), self._result.programme_count,
                    self._matched, matched_by_name,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced on dashboard
                self._error = str(exc)
                log.error("EPG load failed: %s", exc)
                if self._result is None:
                    self._result = epg.EpgResult(epg.EMPTY_XMLTV, set(), 0)
            return self._result

    def invalidate(self) -> None:
        with self._lock:
            self._fetched_at = float("-inf")  # always stale; see ChannelCache

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

    @app.get("/api/update/check")
    def api_update_check() -> Response:
        from . import selfupdate

        return jsonify(selfupdate.check())

    @app.post("/api/update/apply")
    def api_update_apply() -> Response:
        from . import selfupdate

        try:
            result = selfupdate.apply()
        except Exception as exc:  # noqa: BLE001 - surfaced to console
            log.error("Self-update failed: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500
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

    @app.get("/docs/")
    def docs_index() -> Response:
        return _serve_doc("index.html")

    @app.get("/docs/<path:filename>")
    def docs_file(filename: str) -> Response:
        return _serve_doc(filename)

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
                "epg_overrides": config.epg_overrides,
            }
        )

    @app.get("/api/epg/guide-channels")
    def api_guide_channels() -> Response:
        guide.get()  # ensure the guide is built so the index is populated
        return jsonify(guide.guide_channels)

    @app.post("/api/epg/map")
    def api_epg_map() -> Response:
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        tvg_id = (body.get("tvg_id") or "").strip()
        overrides = dict(config.epg_overrides or {})
        if tvg_id:
            overrides[name] = tvg_id
        else:
            overrides.pop(name, None)  # empty id clears the mapping
        config.epg_overrides = overrides
        _save_and_refresh()
        return jsonify({"ok": True, "epg_overrides": config.epg_overrides})

    @app.get("/api/presets")
    def api_presets() -> Response:
        existing = {(s.get("url") or "").strip() for s in config.sources}
        return jsonify(
            [
                {
                    "id": p["id"],
                    "label": p["label"],
                    "region": p["region"],
                    "added": p["url"] in existing,
                }
                for p in presets.PRESETS
            ]
        )

    @app.post("/api/sources")
    def api_add_source() -> Response:
        body = request.get_json(silent=True) or {}

        # One-click preset: look up a curated source by id.
        preset_id = (body.get("preset") or "").strip()
        if preset_id:
            preset = presets.get(preset_id)
            if not preset:
                return jsonify({"error": f"unknown preset {preset_id!r}"}), 400
            if any((s.get("url") or "").strip() == preset["url"] for s in config.sources):
                return jsonify({"ok": True, "sources": config.sources})  # idempotent
            config.sources.append(
                {
                    "name": preset["name"],
                    "url": preset["url"],
                    "group": preset["group"],
                    "type": "m3u",
                }
            )
            _save_and_refresh()
            return jsonify({"ok": True, "sources": config.sources})

        url = (body.get("url") or "").strip()
        if not url:
            return jsonify({"error": "url is required"}), 400
        stype = (body.get("type") or "m3u").lower()
        config.sources.append(
            {
                "name": (body.get("name") or "").strip(),
                "url": url,
                "group": (body.get("group") or "").strip(),
                "type": "hdhr" if stype == "hdhr" else "m3u",
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
            # Be forgiving: a user may paste several URLs on one line (separated
            # by spaces/commas) instead of one per line. Split them apart and
            # de-dupe so a single line never becomes one broken URL.
            urls: list[str] = []
            seen: set[str] = set()
            for entry in body["epg_urls"]:
                for part in re.split(r"[\s,]+", str(entry)):
                    part = part.strip()
                    if part and part not in seen:
                        seen.add(part)
                        urls.append(part)
            config.epg_urls = urls
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
