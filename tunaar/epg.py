"""XMLTV electronic program guide (EPG) handling.

Fetches an XMLTV document (plain or gzip-compressed), optionally filters it
down to just the channels present in the current lineup, and reports how many
lineup channels were matched by ``tvg-id``. The filtered XMLTV is served to
Plex / Emby / Jellyfin as the guide source.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

EMPTY_XMLTV = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<tv generator-info-name="Tunaar"></tv>\n'
)


@dataclass
class EpgResult:
    """Outcome of building the guide."""

    xml: bytes
    channel_ids: set[str]
    programme_count: int


def fetch(source: str, *, user_agent: str = "Tunaar", timeout: int = 60) -> bytes:
    """Load an XMLTV document from a URL or local file, decompressing gzip."""
    if source.startswith(("http://", "https://")):
        resp = requests.get(source, timeout=timeout, headers={"User-Agent": user_agent})
        resp.raise_for_status()
        raw = resp.content
    else:
        with open(source, "rb") as fh:
            raw = fh.read()
    if source.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def build(
    raw_xml: bytes,
    *,
    keep_ids: set[str] | None = None,
) -> EpgResult:
    """Parse XMLTV ``raw_xml`` and optionally filter it to ``keep_ids``.

    When ``keep_ids`` is given, only ``<channel>`` and ``<programme>`` elements
    referencing those ids are retained. Returns the (possibly filtered) XMLTV
    along with the set of channel ids actually present and a programme count.
    """
    root = ET.fromstring(raw_xml)

    channel_ids: set[str] = set()
    programme_count = 0

    for child in list(root):
        if child.tag == "channel":
            cid = child.get("id", "")
            if keep_ids is not None and cid not in keep_ids:
                root.remove(child)
                continue
            channel_ids.add(cid)
        elif child.tag == "programme":
            cid = child.get("channel", "")
            if keep_ids is not None and cid not in keep_ids:
                root.remove(child)
                continue
            programme_count += 1

    root.set("generator-info-name", "Tunaar")
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )
    return EpgResult(xml=xml, channel_ids=channel_ids, programme_count=programme_count)
