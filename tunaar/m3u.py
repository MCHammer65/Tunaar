# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parsing of extended M3U (M3U8) IPTV playlists."""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass, field

import requests

from . import netguard

log = logging.getLogger("tunaar")

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_EXTINF_RE = re.compile(r"#EXTINF:-?\d+\s*(?P<attrs>.*?),(?P<name>.*)$")

UNGROUPED = "Undefined"


@dataclass
class Channel:
    """A single playlist entry."""

    number: str
    name: str
    url: str
    logo: str = ""
    group: str = ""
    tvg_id: str = ""
    source: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class Playlist:
    """Parsed playlist: its channels plus any embedded EPG URLs."""

    channels: list[Channel]
    epg_urls: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # sources that couldn't load


def parse_document(text: str, *, source: str = "") -> Playlist:
    """Parse extended M3U ``text`` without assigning channel numbers.

    Also extracts any EPG URL declared in the ``#EXTM3U`` header via the
    ``url-tvg`` or ``x-tvg-url`` attribute, which most providers include.
    """
    channels: list[Channel] = []
    epg_urls: list[str] = []
    pending: Channel | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            epg_urls.extend(_header_epg_urls(line))
        elif line.startswith("#EXTINF"):
            pending = _parse_extinf(line)
            pending.source = source
        elif line.startswith("#"):
            continue  # other directives (#EXTGRP etc.) — ignored
        elif pending is not None:
            pending.url = line
            channels.append(pending)
            pending = None

    return Playlist(channels=channels, epg_urls=epg_urls)


def parse(text: str) -> list[Channel]:
    """Parse ``text`` and assign guide numbers (convenience for single lists)."""
    return assign_numbers(parse_document(text).channels)


def _header_epg_urls(line: str) -> list[str]:
    attrs = dict(_ATTR_RE.findall(line))
    raw = attrs.get("url-tvg") or attrs.get("x-tvg-url") or ""
    return [u.strip() for u in raw.split(",") if u.strip()]


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
        group=attrs.get("group-title", "") or UNGROUPED,
        tvg_id=attrs.get("tvg-id", ""),
        attrs=attrs,
    )


def assign_numbers(channels: list[Channel]) -> list[Channel]:
    """Assign collision-free guide numbers, honouring ``tvg-chno`` when set."""
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


def _fetch_text(source: str, *, user_agent: str, timeout: int) -> str:
    if source.startswith(("http://", "https://")):
        netguard.check_url(source)
        resp = requests.get(
            source, timeout=timeout, headers={"User-Agent": user_agent}
        )
        resp.raise_for_status()
        return resp.text
    with open(source, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def load(source: str, *, user_agent: str = "Tunaar", timeout: int = 30) -> list[Channel]:
    """Load and parse a single playlist from a URL or local file."""
    text = _fetch_text(source, user_agent=user_agent, timeout=timeout)
    return parse(text)


def derive_epg_url(m3u_url: str) -> str | None:
    """Derive an Xtream Codes XMLTV URL from a ``get.php`` playlist URL.

    Xtream/IPTV panels expose the playlist at ``.../get.php?username=..&password=..``
    and the matching guide at ``.../xmltv.php?username=..&password=..``. Returns
    the guide URL when the input matches that pattern, else ``None``.
    """
    if "get.php" not in m3u_url.lower():
        return None
    split = urllib.parse.urlsplit(m3u_url)
    if "get.php" not in split.path.lower():
        return None
    qs = urllib.parse.parse_qs(split.query)
    user = (qs.get("username") or [""])[0]
    pwd = (qs.get("password") or [""])[0]
    if not user or not pwd:
        return None
    path = re.sub(r"get\.php$", "xmltv.php", split.path, flags=re.IGNORECASE)
    query = urllib.parse.urlencode({"username": user, "password": pwd})
    return urllib.parse.urlunsplit((split.scheme, split.netloc, path, query, ""))


def load_sources(
    sources: list[dict],
    *,
    user_agent: str = "Tunaar",
    timeout: int = 30,
) -> Playlist:
    """Load and merge several playlists.

    Each source is a dict with ``url`` (required) and optional ``name`` /
    ``group`` (a group override applied to all of that source's channels) /
    ``type`` (``"m3u"`` default, or ``"hdhr"`` for a real HDHomeRun device).
    Numbers are assigned across the merged set so every channel is unique, and
    embedded EPG URLs from all sources are collected.
    """
    merged: list[Channel] = []
    epg_urls: list[str] = []
    failed: list[str] = []

    for src in sources:
        url = (src.get("url") or "").strip()
        if not url:
            continue
        name = src.get("name") or url
        override = (src.get("group") or "").strip()
        stype = (src.get("type") or "m3u").lower()
        try:
            limit = int(src.get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0

        # One bad/unreachable source must not abort the whole merge — skip it.
        try:
            if stype == "hdhr":
                chans = load_hdhr(
                    url, user_agent=user_agent, timeout=timeout,
                    clean=bool(src.get("clean")),
                )
                for ch in chans:
                    ch.source = name
                    ch.group = override or "Freeview"
                if limit > 0:
                    chans = chans[:limit]
                merged.extend(chans)
                continue

            text = _fetch_text(url, user_agent=user_agent, timeout=timeout)
            doc = parse_document(text, source=name)
            if override:
                for ch in doc.channels:
                    ch.group = override
            chans = doc.channels[:limit] if limit > 0 else doc.channels
            merged.extend(chans)
            epg_urls.extend(doc.epg_urls)
        except Exception as exc:  # noqa: BLE001 - per-source, non-fatal
            failed.append(url)
            log.warning("Source failed, skipping: %s (%s)", url, exc)

    assign_numbers(merged)
    # De-duplicate EPG URLs, preserving order.
    seen: set[str] = set()
    unique_epg = [u for u in epg_urls if not (u in seen or seen.add(u))]
    return Playlist(channels=merged, epg_urls=unique_epg, failed=failed)


# Keywords that mark a shopping channel (matched case-insensitively in the name).
_SHOPPING_HINTS = (
    "qvc", "ideal world", "gemporia", "gems tv", "tjc", "hochanda", "craft",
    "hobbymaker", "jewell", "shop", "high street tv", "must have ideas", "ideal",
)


def _hdhr_skip(item: dict, clean: bool) -> bool:
    """Whether a HDHomeRun lineup item should be dropped when ``clean`` is set."""
    if not clean:
        return False
    name = (item.get("GuideName") or "").lower()
    # Radio / audio-only: has an audio codec but no video codec.
    if "AudioCodec" in item and "VideoCodec" not in item:
        return True
    if "adult" in name:
        return True
    if "+1" in name:  # timeshift duplicates
        return True
    if any(h in name for h in _SHOPPING_HINTS):
        return True
    return False


def load_hdhr(
    url: str,
    *,
    user_agent: str = "Tunaar",
    timeout: int = 30,
    clean: bool = False,
) -> list[Channel]:
    """Read a real HDHomeRun device's ``lineup.json`` into channels.

    ``url`` may be the device base (``http://192.168.1.50``), its
    ``discover.json``, or its ``lineup.json``. HDHomeRun stream URLs are plain
    MPEG-TS, so Tunaar's normal proxy/ffmpeg path handles them unchanged.

    When ``clean`` is set, radio/audio-only, adult, shopping and ``+1``
    timeshift channels are skipped to keep the TV lineup tidy.
    """
    headers = {"User-Agent": user_agent}
    # (connect, read): fail fast if the device is unreachable so an offline/
    # wrong HDHomeRun address can't stall the whole playlist rebuild.
    to = (5, min(timeout, 15))
    base = url.rstrip("/")
    netguard.check_url(base)
    if base.endswith("lineup.json"):
        lineup_url = base
    elif base.endswith("discover.json"):
        disc = requests.get(base, timeout=to, headers=headers).json()
        lineup_url = disc.get("LineupURL") or base.rsplit("/", 1)[0] + "/lineup.json"
    else:
        lineup_url = base + "/lineup.json"

    netguard.check_url(lineup_url)
    data = requests.get(lineup_url, timeout=to, headers=headers).json()
    channels: list[Channel] = []
    for item in data:
        if _hdhr_skip(item, clean):
            continue
        number = str(item.get("GuideNumber", "")).strip()
        channels.append(
            Channel(
                number="",
                name=item.get("GuideName", "Unknown"),
                url=item.get("URL", ""),
                group="",
                tvg_id="",
                attrs={"tvg-chno": number} if number else {},
            )
        )
    return channels

