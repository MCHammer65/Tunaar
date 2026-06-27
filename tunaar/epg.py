# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""XMLTV electronic program guide (EPG) handling.

Fetches an XMLTV document (plain or gzip-compressed), optionally filters it
down to just the channels present in the current lineup, and reports how many
lineup channels were matched by ``tvg-id``. The filtered XMLTV is served to
Plex / Emby / Jellyfin as the guide source.
"""

from __future__ import annotations

import copy
import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date

import requests

from . import netguard

EMPTY_XMLTV = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<tv generator-info-name="Tunaar"></tv>\n'
)

# Many public EPG hosts 404/403 non-browser agents, so fetch guides as a browser.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class EpgResult:
    """Outcome of building the guide."""

    xml: bytes
    channel_ids: set[str]
    programme_count: int
    name_to_id: dict = field(default_factory=dict)
    id_to_name: dict = field(default_factory=dict)


def norm_name(name: str) -> str:
    """Normalise a channel name for fuzzy matching (drops HD/quality/spaces)."""
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)  # drop "(1080p)" etc.
    s = re.sub(r"\b(hd|sd|fhd|uhd|4k|hevc|h265)\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def fetch(source: str, *, user_agent: str | None = None, timeout: int = 60) -> bytes:
    """Load an XMLTV document from a URL or local file, decompressing gzip.

    Defaults to a browser-like User-Agent because several public EPG hosts
    (e.g. epgshare01) return 404/403 to non-browser agents.
    """
    if source.startswith(("http://", "https://")):
        netguard.check_url(source)
        headers = {"User-Agent": user_agent or BROWSER_UA}
        resp = requests.get(source, timeout=timeout, headers=headers)
        resp.raise_for_status()
        raw = resp.content
    else:
        with open(source, "rb") as fh:
            raw = fh.read()
    if source.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def _has_episode_num(programme) -> bool:
    """True if the programme carries a real season/episode number."""
    for el in programme.findall("episode-num"):
        if el.text and any(ch.isdigit() for ch in el.text):
            return True
    return False


def _day_of_year(start: str) -> tuple[int, int] | None:
    """Parse an XMLTV ``start`` ("YYYYMMDDhhmmss …") into ``(year, day_of_year)``.

    Returns ``None`` if the timestamp is missing or unparseable.
    """
    if not start or len(start) < 8 or not start[:8].isdigit():
        return None
    try:
        d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    except ValueError:
        return None
    return d.year, d.timetuple().tm_yday


def _disambiguate(programme, seq: dict) -> None:
    """Make an airing distinguishable to Plex without cluttering its title.

    Plex's DVR shares one description across every programme with an identical
    ``<title>`` (e.g. "News" or "Paid Programming" on many channels/airings),
    so identical-titled airings collapse into one. We break that tie:

    * Programmes that already carry a real ``<episode-num>`` are left alone —
      Plex distinguishes those by season/episode.
    * When a ``<sub-title>`` is present (typically live sports, e.g.
      "Team A vs Team B"), it's folded into the title ("Title — Sub") so the
      matchup shows in the guide.
    * Otherwise (news, movies, paid programming, music …) we inject a synthetic
      date-based ``<episode-num>`` — Julian day of the airing — so each day's
      airing is unique while the title stays clean. Multiple distinct airings
      on the same day get an incrementing part (``S2026E178``, ``S2026E178.2``).
    """
    if _has_episode_num(programme):
        return

    title_el = programme.find("title")
    if title_el is None or title_el.text is None:
        return
    title = title_el.text.strip()

    sub_el = programme.find("sub-title")
    sub = (sub_el.text or "").strip() if sub_el is not None else ""
    if sub and sub.lower() != title.lower() and " — " not in title:
        title_el.text = f"{title} — {sub}"
        return

    ymd = _day_of_year(programme.get("start", ""))
    if ymd is None:
        return
    year, doy = ymd

    key = (programme.get("channel", ""), title.lower(), year, doy)
    n = seq.get(key, 0)
    seq[key] = n + 1

    # xmltv_ns is 0-indexed "season.episode.part"; onscreen is human-readable.
    ns = ET.SubElement(programme, "episode-num")
    ns.set("system", "xmltv_ns")
    ns.text = f"{year - 1}.{doy - 1}.{n}"

    onscreen = ET.SubElement(programme, "episode-num")
    onscreen.set("system", "onscreen")
    onscreen.text = f"S{year}E{doy:03d}" + (f".{n + 1}" if n else "")


def _set_icon(channel_el, logo: str) -> None:
    """Add an ``<icon src>`` to a channel so logos show in every player.

    No-op when there's no logo or the channel already carries an icon (the
    guide's own logo wins over the lineup's).
    """
    if not logo or channel_el.find("icon") is not None:
        return
    ET.SubElement(channel_el, "icon").set("src", logo)


def _apply_tz(programme, offset: str) -> None:
    """Stamp a timezone ``offset`` (e.g. "+0000") onto bare programme times.

    XMLTV times should carry an offset ("20260627060000 +0000"); feeds that
    omit it make players guess and drift. Only offset-less, all-digit
    timestamps are touched — times that already declare an offset are left as-is.
    """
    for attr in ("start", "stop"):
        val = (programme.get(attr) or "").strip()
        if val and val.isdigit():
            programme.set(attr, f"{val} {offset}")


def build_many(
    raw_docs: list[bytes],
    *,
    keep_ids: set[str] | None = None,
    unique_titles: bool = False,
    logos: dict | None = None,
    tz_offset: str = "",
) -> EpgResult:
    """Merge several XMLTV documents into one, then optionally filter.

    Channels are de-duplicated by id across documents; programmes are kept for
    any retained channel. Parse errors in one document don't sink the rest.
    """
    root = ET.Element("tv")
    root.set("generator-info-name", "Tunaar")
    seen_channels: set[str] = set()

    for raw in raw_docs:
        try:
            doc = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for child in list(doc):
            if child.tag == "channel":
                cid = child.get("id", "")
                if cid in seen_channels:
                    continue
                seen_channels.add(cid)
                root.append(child)
            elif child.tag == "programme":
                root.append(child)

    merged = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )
    return build(merged, keep_ids=keep_ids, unique_titles=unique_titles,
                 logos=logos, tz_offset=tz_offset)


def align(
    raw_xml: bytes,
    number_to_id: dict[str, str],
    *,
    unique_titles: bool = False,
    logos: dict | None = None,
    tz_offset: str = "",
) -> EpgResult:
    """Re-key the guide so every lineup channel *number* is its own ``<channel>``.

    ``number_to_id`` maps a lineup channel number to the guide channel id it
    matched (by tvg-id, name, or a manual override). For each entry, the matched
    guide ``<channel>`` and its ``<programme>`` elements are cloned with the
    channel id rewritten to the lineup number, and the number is also added as a
    ``<display-name>``.

    This guarantees Plex / Emby / Jellyfin attach guide data by channel number
    with no manual mapping — the tuner's ``GuideNumber`` and the XMLTV channel id
    are then identical. A guide channel matched by several lineup numbers is
    duplicated, one copy per number, so nothing is lost.
    """
    root = ET.fromstring(raw_xml)
    src_channels: dict = {}
    src_programmes: dict = {}
    for child in list(root):
        if child.tag == "channel":
            src_channels[child.get("id", "")] = child
        elif child.tag == "programme":
            src_programmes.setdefault(child.get("channel", ""), []).append(child)

    channel_els: list = []
    programme_els: list = []
    channel_ids: set[str] = set()
    name_to_id: dict = {}
    id_to_name: dict = {}
    seq: dict = {}

    for number, gid in number_to_id.items():
        new_ch = ET.Element("channel")
        new_ch.set("id", number)
        src_ch = src_channels.get(gid)
        if src_ch is not None:
            for sub in list(src_ch):
                new_ch.append(copy.deepcopy(sub))
            for dn in src_ch.findall("display-name"):
                if dn.text:
                    name_to_id.setdefault(norm_name(dn.text), number)
                    id_to_name.setdefault(number, dn.text.strip())
        # The channel number as an extra display-name, so players that match on
        # number (not just on id) attach too.
        ET.SubElement(new_ch, "display-name").text = number
        if logos:
            _set_icon(new_ch, logos.get(number, ""))
        channel_els.append(new_ch)
        channel_ids.add(number)

        for prog in src_programmes.get(gid, []):
            clone = copy.deepcopy(prog)
            clone.set("channel", number)
            if unique_titles:
                _disambiguate(clone, seq)
            if tz_offset:
                _apply_tz(clone, tz_offset)
            programme_els.append(clone)

    out = ET.Element("tv")
    out.set("generator-info-name", "Tunaar")
    out.extend(channel_els)
    out.extend(programme_els)

    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        out, encoding="utf-8"
    )
    return EpgResult(
        xml=xml,
        channel_ids=channel_ids,
        programme_count=len(programme_els),
        name_to_id=name_to_id,
        id_to_name=id_to_name,
    )


def build(
    raw_xml: bytes,
    *,
    keep_ids: set[str] | None = None,
    unique_titles: bool = False,
    logos: dict | None = None,
    tz_offset: str = "",
) -> EpgResult:
    """Parse XMLTV ``raw_xml`` and optionally filter it to ``keep_ids``.

    When ``keep_ids`` is given, only ``<channel>`` and ``<programme>`` elements
    referencing those ids are retained. When ``unique_titles`` is set, each
    programme is disambiguated (see :func:`_disambiguate`) so Plex can't
    collapse descriptions across airings that share a title. Returns the
    (possibly filtered) XMLTV along with the set of channel ids actually
    present and a programme count.
    """
    root = ET.fromstring(raw_xml)

    channel_ids: set[str] = set()
    name_to_id: dict = {}
    id_to_name: dict = {}
    programme_count = 0
    seq: dict = {}

    for child in list(root):
        if child.tag == "channel":
            cid = child.get("id", "")
            if keep_ids is not None and cid not in keep_ids:
                root.remove(child)
                continue
            channel_ids.add(cid)
            for dn in child.findall("display-name"):
                if dn.text:
                    name_to_id.setdefault(norm_name(dn.text), cid)
                    id_to_name.setdefault(cid, dn.text.strip())
            if logos:
                _set_icon(child, logos.get(cid, ""))
        elif child.tag == "programme":
            cid = child.get("channel", "")
            if keep_ids is not None and cid not in keep_ids:
                root.remove(child)
                continue
            programme_count += 1
            if unique_titles:
                _disambiguate(child, seq)
            if tz_offset:
                _apply_tz(child, tz_offset)

    root.set("generator-info-name", "Tunaar")
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )
    return EpgResult(
        xml=xml,
        channel_ids=channel_ids,
        programme_count=programme_count,
        name_to_id=name_to_id,
        id_to_name=id_to_name,
    )
