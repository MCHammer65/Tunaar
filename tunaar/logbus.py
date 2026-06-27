# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory log bus powering the admin console's live activity feed.

Tunaar events are published here (also wired into the stdlib ``logging`` via
:class:`BusHandler`). The console reads recent records over ``/api/logs`` and
subscribes to new ones over Server-Sent Events. Everything is bounded so a
long-running container never grows unbounded.
"""

from __future__ import annotations

import logging
import queue
import threading
import time


class LogBus:
    def __init__(self, capacity: int = 500) -> None:
        self._buf: list[dict] = []
        self._capacity = capacity
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._seq = 0

    def publish(self, level: str, message: str) -> dict:
        with self._lock:
            self._seq += 1
            rec = {"id": self._seq, "t": time.time(), "level": level, "msg": message}
            self._buf.append(rec)
            if len(self._buf) > self._capacity:
                self._buf = self._buf[-self._capacity :]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(rec)
            except queue.Full:
                pass
        return rec

    def recent(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self._buf[-limit:])

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


class BusHandler(logging.Handler):
    """Routes stdlib log records into a :class:`LogBus`."""

    def __init__(self, bus: LogBus) -> None:
        super().__init__()
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bus.publish(record.levelname, record.getMessage())
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
