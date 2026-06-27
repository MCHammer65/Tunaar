# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stream proxying with real tuner-slot accounting.

Two robustness wins over a bare redirect:

* **Tuner slots** — a fixed pool (``tuner_count``) is enforced, so Plex never
  opens more concurrent streams than the device claims to support. Slots are
  released deterministically when the client disconnects.
* **ffmpeg remux** — by default each stream is piped through ffmpeg
  (``-c copy -f mpegts``) with reconnection enabled. This normalises HLS and
  flaky sources into a clean MPEG-TS that players consume reliably, which is the
  main cause of "hit and miss" playback elsewhere.

``direct`` mode passes the upstream bytes through unchanged; ``redirect`` mode
(handled by the caller) just 302s to the source and does not consume a slot.
"""

from __future__ import annotations

import itertools
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

import requests


@dataclass
class TunerSession:
    id: int
    channel_number: str
    channel_name: str
    started_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "channel": self.channel_number,
            "name": self.channel_name,
            "uptime": round(time.time() - self.started_at, 1),
        }


class TunersBusy(Exception):
    """Raised when every tuner slot is already in use."""


class TunerManager:
    """Tracks active tuner sessions against a fixed capacity."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._lock = threading.Lock()
        self._sessions: dict[int, TunerSession] = {}
        self._ids = itertools.count(1)

    def acquire(self, channel_number: str, channel_name: str) -> TunerSession:
        with self._lock:
            if len(self._sessions) >= self.capacity:
                raise TunersBusy(
                    f"all {self.capacity} tuner(s) in use"
                )
            session = TunerSession(
                id=next(self._ids),
                channel_number=channel_number,
                channel_name=channel_name,
            )
            self._sessions[session.id] = session
            return session

    def release(self, session: TunerSession) -> None:
        with self._lock:
            self._sessions.pop(session.id, None)

    def active(self) -> list[dict]:
        with self._lock:
            return [s.as_dict() for s in self._sessions.values()]

    @property
    def in_use(self) -> int:
        with self._lock:
            return len(self._sessions)


def ffmpeg_available(ffmpeg_path: str = "ffmpeg") -> bool:
    return shutil.which(ffmpeg_path) is not None


def build_ffmpeg_cmd(url: str, *, ffmpeg_path: str, user_agent: str) -> list[str]:
    """ffmpeg command that remuxes ``url`` to an MPEG-TS stream on stdout."""
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel", "error",
        "-user_agent", user_agent,
        # Reconnect to the source if it drops mid-stream.
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", url,
        "-c", "copy",
        "-f", "mpegts",
        "-mpegts_copyts", "1",
        "pipe:1",
    ]


def ffmpeg_stream(url: str, *, ffmpeg_path: str, user_agent: str, chunk: int):
    """Yield MPEG-TS bytes from an ffmpeg subprocess remuxing ``url``."""
    cmd = build_ffmpeg_cmd(url, ffmpeg_path=ffmpeg_path, user_agent=user_agent)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )
    try:
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read(chunk)
            if not data:
                break
            yield data
    finally:
        _terminate(proc)


def direct_stream(
    url: str, *, user_agent: str, chunk: int, reconnects: int = 3
):
    """Pass upstream bytes through unchanged, retrying on a dropped connection."""
    attempt = 0
    while True:
        try:
            with requests.get(
                url,
                stream=True,
                timeout=(10, 30),
                headers={"User-Agent": user_agent},
            ) as resp:
                resp.raise_for_status()
                for data in resp.iter_content(chunk_size=chunk):
                    if data:
                        yield data
            return  # upstream ended cleanly
        except (requests.RequestException, OSError):
            attempt += 1
            if attempt > reconnects:
                return
            time.sleep(min(2 ** attempt, 5))


def supervised(candidates, *, max_retries: int = 20, settle: float = 10.0):
    """Supervise one or more upstream sources, keeping the client fed.

    ``candidates`` is a list of zero-arg factories, each returning a *fresh*
    byte generator (a new ffmpeg/direct pull) for one upstream. They are tried
    in priority order:

    * When a source ends while the client is still connected, a new attempt is
      started so the feed stays continuous (auto-reconnect).
    * A source that delivered data and ran at least ``settle`` seconds is
      healthy — the failure budget resets and we stay on it.
    * A source that dies quickly counts down ``max_retries`` (capped backoff)
      and, when more than one candidate exists, **fails over to the next**
      provider — so a dead source moves on to a live one.
    * Client disconnect propagates ``GeneratorExit`` through and stops cleanly,
      with no restart.
    """
    if not candidates:
        return
    failures = 0
    idx = 0
    n = len(candidates)
    while True:
        started = time.time()
        produced = False
        source = candidates[idx]()
        try:
            for data in source:
                produced = True
                yield data
        finally:
            # Closing the source on any exit (incl. client disconnect) tears
            # down the ffmpeg process / upstream connection deterministically.
            close = getattr(source, "close", None)
            if close is not None:
                close()
        if produced and (time.time() - started) >= settle:
            failures = 0  # healthy run — stay on this working source
        else:
            failures += 1
            if n > 1:
                idx = (idx + 1) % n  # fail over to the next provider
            if failures > max_retries:
                return
        time.sleep(min(2 ** min(failures, 3), 5))


def stabilize(make_source, *, max_retries: int = 20, settle: float = 10.0):
    """Single-source supervisor — :func:`supervised` with one candidate."""
    return supervised([make_source], max_retries=max_retries, settle=settle)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def probe(url: str, *, user_agent: str, timeout: int = 10) -> dict:
    """Quickly test an upstream URL without consuming a tuner slot.

    Opens the stream, reads a small chunk, and reports timing/status so the
    console can tell a live channel from a dead one.
    """
    start = time.time()
    try:
        with requests.get(
            url, stream=True, timeout=timeout, headers={"User-Agent": user_agent}
        ) as resp:
            ok = resp.ok
            chunk = next(resp.iter_content(chunk_size=8192), b"")
            return {
                "ok": bool(ok and chunk),
                "status": resp.status_code,
                "content_type": resp.headers.get("Content-Type", ""),
                "bytes": len(chunk),
                "ms": round((time.time() - start) * 1000),
            }
    except Exception as exc:  # noqa: BLE001 - surfaced to the console
        return {
            "ok": False,
            "error": str(exc),
            "ms": round((time.time() - start) * 1000),
        }

