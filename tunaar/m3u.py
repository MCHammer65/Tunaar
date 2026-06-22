"""Parsing of extended M3U (M3U8) IPTV playlists."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_EXTINF_RE = re.compile(r"#EXTINF:-?\d+\s*(?P<attrs>.*?),(?P<name>.*)$")


@dataclass
class Channel:
    """A single playlist entry."""

    number: str
    name: str
    url: str
    logo: str = ""
    group: str = ""
    tvg_id: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


def parse(text: str) -> list[Channel]:
    """Parse extended M3U ``text`` into a list of :class:`Channel`.

    Guide numbers come from ``tvg-chno`` when present, otherwise channels are
    numbered sequentially. Numbers are de-duplicated so each channel is
    uniquely addressable.
    """
    channels: list[Channel] = []
    pending: Channel | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "#EXTM3U":
            continue
        if line.startswith("#EXTINF"):
            pending = _parse_extinf(line)
        elif line.startswith("#"):
            continue  # other directives (#EXTGRP etc.) — ignored
        elif pending is not None:
            pending.url = line
            channels.append(pending)
            pending = None

    return _assign_numbers(channels)


def _parse_extinf(line: str) -> Channel:
    match = _EXTINF_RE.match(line)
    if match:
        attrs = dict(_ATTR_RE.findall(match.group("attrs")))
        name = match.group("name").strip()
    else:
        attrs = {}
        name = line.split(",", 1)[-1].strip()

    return Channel(
        number="",
        name=name or attrs.get("tvg-name", "Unknown"),
        url="",
        logo=attrs.get("tvg-logo", ""),
        group=attrs.get("group-title", ""),
        tvg_id=attrs.get("tvg-id", ""),
        attrs=attrs,
    )


def _assign_numbers(channels: list[Channel]) -> list[Channel]:
    used: set[str] = set()
    next_auto = 1

    for ch in channels:
        number = ch.attrs.get("tvg-chno", "").strip()
        if not number or number in used:
            while str(next_auto) in used:
                next_auto += 1
            number = str(next_auto)
            next_auto += 1
        used.add(number)
        ch.number = number

    return channels


def load(source: str, *, user_agent: str = "Tunaar", timeout: int = 30) -> list[Channel]:
    """Load and parse a playlist from a URL or local file ``source``."""
    if source.startswith(("http://", "https://")):
        resp = requests.get(
            source, timeout=timeout, headers={"User-Agent": user_agent}
        )
        resp.raise_for_status()
        text = resp.text
    else:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    return parse(text)
