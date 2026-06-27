"""XMLTV electronic program guide (EPG) handling.

Fetches an XMLTV document (plain or gzip-compressed), optionally filters it
down to just the channels present in the current lineup, and reports how many
lineup channels were matched by ``tvg-id``. The filtered XMLTV is served to
Plex / Emby / Jellyfin as the guide source.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

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


def _disambiguator(programme) -> str:
    """A short string that distinguishes this airing — sub-title, else a
    trimmed first line of the description."""
    sub_el = programme.find("sub-title")
    sub = (sub_el.text or "").strip() if sub_el is not None else ""
    if sub:
        return sub
    desc_el = programme.find("desc")
    desc = (desc_el.text or "").strip() if desc_el is not None else ""
    if not desc:
        return ""
    # First sentence/line only, capped so titles stay readable.
    snippet = re.split(r"(?<=[.!?])\s|\n", desc, maxsplit=1)[0].strip()
    if len(snippet) > 70:
        snippet = snippet[:69].rstrip() + "…"
    return snippet


def _has_episode_num(programme) -> bool:
    """True if the programme carries a real season/episode number."""
    for el in programme.findall("episode-num"):
        if el.text and any(ch.isdigit() for ch in el.text):
            return True
    return False


def _fold_subtitle(programme) -> None:
    """Append a per-airing disambiguator to a programme's <title> so the title
    is unique.

    Defeats a Plex DVR bug that shares one description across all programmes
    with an identical title (e.g. "MLB Baseball" on many channels). Uses the
    <sub-title> when present, otherwise the first line of the <desc>.

    Episodic content (anything with an <episode-num>) is left alone: Plex
    already distinguishes those by season/episode, so folding the sub-title in
    would only clutter the guide.
    """
    title_el = programme.find("title")
    if title_el is None or title_el.text is None:
        return
    if _has_episode_num(programme):
        return
    title = title_el.text.strip()
    extra = _disambiguator(programme)
    if extra and extra.lower() != title.lower() and " — " not in title:
        title_el.text = f"{title} — {extra}"


def build_many(
    raw_docs: list[bytes],
    *,
    keep_ids: set[str] | None = None,
    unique_titles: bool = False,
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
    return build(merged, keep_ids=keep_ids, unique_titles=unique_titles)


def build(
    raw_xml: bytes,
    *,
    keep_ids: set[str] | None = None,
    unique_titles: bool = False,
) -> EpgResult:
    """Parse XMLTV ``raw_xml`` and optionally filter it to ``keep_ids``.

    When ``keep_ids`` is given, only ``<channel>`` and ``<programme>`` elements
    referencing those ids are retained. When ``unique_titles`` is set, each
    programme's ``<sub-title>`` is folded into its ``<title>`` ("Title — Sub")
    so Plex can't collapse descriptions across airings that share a title.
    Returns the (possibly filtered) XMLTV along with the set of channel ids
    actually present and a programme count.
    """
    root = ET.fromstring(raw_xml)

    channel_ids: set[str] = set()
    name_to_id: dict = {}
    id_to_name: dict = {}
    programme_count = 0

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
        elif child.tag == "programme":
            cid = child.get("channel", "")
            if keep_ids is not None and cid not in keep_ids:
                root.remove(child)
                continue
            programme_count += 1
            if unique_titles:
                _fold_subtitle(child)

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
