# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Curated source presets for one-click setup.

Each preset is a normal M3U source. The mjh.nz playlists advertise their
matching XMLTV guide in the ``#EXTM3U`` header (``url-tvg``), so with
``epg_auto`` on (the default) the guide is discovered automatically — adding a
preset gives you both the channels and their guide with no extra typing.

These are third-party community lists; paths can change over time. The index
pages at https://i.mjh.nz/ list every region's current links.
"""

# Country playlists from the iptv-org project. mjh.nz dropped its Samsung/Pluto
# M3U playlists (it now serves only EPG guides), so presets point at iptv-org's
# maintained per-country lists instead. These are community-indexed public
# streams; coverage and reliability vary, and a dead source is skipped, not fatal.
PRESETS: list[dict] = [
    {
        "id": "uk",
        "label": "United Kingdom",
        "region": "GB",
        "name": "United Kingdom (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/uk.m3u",
        "group": "United Kingdom",
    },
    {
        "id": "us",
        "label": "United States",
        "region": "US",
        "name": "United States (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/us.m3u",
        "group": "United States",
    },
    {
        "id": "ca",
        "label": "Canada",
        "region": "CA",
        "name": "Canada (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/ca.m3u",
        "group": "Canada",
    },
    {
        "id": "fr",
        "label": "France",
        "region": "FR",
        "name": "France (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/fr.m3u",
        "group": "France",
    },
    {
        "id": "de",
        "label": "Germany",
        "region": "DE",
        "name": "Germany (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/de.m3u",
        "group": "Germany",
    },
    {
        "id": "es",
        "label": "Spain",
        "region": "ES",
        "name": "Spain (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/es.m3u",
        "group": "Spain",
    },
    {
        "id": "it",
        "label": "Italy",
        "region": "IT",
        "name": "Italy (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/it.m3u",
        "group": "Italy",
    },
    {
        "id": "br",
        "label": "Brazil",
        "region": "BR",
        "name": "Brazil (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/br.m3u",
        "group": "Brazil",
    },
    {
        "id": "au",
        "label": "Australia",
        "region": "AU",
        "name": "Australia (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/au.m3u",
        "group": "Australia",
    },
    {
        "id": "mx",
        "label": "Mexico",
        "region": "MX",
        "name": "Mexico (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/mx.m3u",
        "group": "Mexico",
    },
    {
        "id": "jm",
        "label": "Jamaica",
        "region": "JM",
        "name": "Jamaica (iptv-org)",
        "url": "https://iptv-org.github.io/iptv/countries/jm.m3u",
        "group": "Jamaica",
    },
]

def get(preset_id: str) -> dict | None:
    """Return the preset with ``id == preset_id``, or ``None``."""
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    return None


# One-click XMLTV guide presets (epgshare01 per-country files). These cover
# broadcast/OTA and many IPTV channels by name. Tunaar fetches them with a
# browser user-agent and skips any that are unreachable, so a dud is harmless.
EPG_PRESETS: list[dict] = [
    {"id": "epg-uk", "label": "UK guide (Freeview etc.)",
     "url": "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz"},
    {"id": "epg-us", "label": "US guide",
     "url": "https://epgshare01.online/epgshare01/epg_ripper_US1.xml.gz"},
    {"id": "epg-ca", "label": "Canada guide",
     "url": "https://epgshare01.online/epgshare01/epg_ripper_CA1.xml.gz"},
    {"id": "epg-fr", "label": "France guide",
     "url": "https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz"},
    {"id": "epg-de", "label": "Germany guide",
     "url": "https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz"},
]


def epg_get(preset_id: str) -> dict | None:
    """Return the EPG preset with ``id == preset_id``, or ``None``."""
    for p in EPG_PRESETS:
        if p["id"] == preset_id:
            return p
    return None
