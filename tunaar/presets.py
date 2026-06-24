"""Curated source presets for one-click setup.

Each preset is a normal M3U source. The mjh.nz playlists advertise their
matching XMLTV guide in the ``#EXTM3U`` header (``url-tvg``), so with
``epg_auto`` on (the default) the guide is discovered automatically — adding a
preset gives you both the channels and their guide with no extra typing.

These are third-party community lists; paths can change over time. The index
pages at https://i.mjh.nz/ list every region's current links.
"""

PRESETS: list[dict] = [
    {
        "id": "samsung-gb",
        "label": "Samsung TV Plus — UK",
        "region": "GB",
        "name": "Samsung TV Plus GB",
        "url": "https://i.mjh.nz/SamsungTVPlus/gb.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-gb",
        "label": "Pluto TV — UK",
        "region": "GB",
        "name": "Pluto TV GB",
        "url": "https://i.mjh.nz/PlutoTV/gb.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-us",
        "label": "Samsung TV Plus — US",
        "region": "US",
        "name": "Samsung TV Plus US",
        "url": "https://i.mjh.nz/SamsungTVPlus/us.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-us",
        "label": "Pluto TV — US",
        "region": "US",
        "name": "Pluto TV US",
        "url": "https://i.mjh.nz/PlutoTV/us.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-ca",
        "label": "Samsung TV Plus — Canada",
        "region": "CA",
        "name": "Samsung TV Plus CA",
        "url": "https://i.mjh.nz/SamsungTVPlus/ca.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-ca",
        "label": "Pluto TV — Canada",
        "region": "CA",
        "name": "Pluto TV CA",
        "url": "https://i.mjh.nz/PlutoTV/ca.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-fr",
        "label": "Samsung TV Plus — France",
        "region": "FR",
        "name": "Samsung TV Plus FR",
        "url": "https://i.mjh.nz/SamsungTVPlus/fr.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-fr",
        "label": "Pluto TV — France",
        "region": "FR",
        "name": "Pluto TV FR",
        "url": "https://i.mjh.nz/PlutoTV/fr.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-de",
        "label": "Samsung TV Plus — Germany",
        "region": "DE",
        "name": "Samsung TV Plus DE",
        "url": "https://i.mjh.nz/SamsungTVPlus/de.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-de",
        "label": "Pluto TV — Germany",
        "region": "DE",
        "name": "Pluto TV DE",
        "url": "https://i.mjh.nz/PlutoTV/de.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-es",
        "label": "Samsung TV Plus — Spain",
        "region": "ES",
        "name": "Samsung TV Plus ES",
        "url": "https://i.mjh.nz/SamsungTVPlus/es.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-es",
        "label": "Pluto TV — Spain",
        "region": "ES",
        "name": "Pluto TV ES",
        "url": "https://i.mjh.nz/PlutoTV/es.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-it",
        "label": "Samsung TV Plus — Italy",
        "region": "IT",
        "name": "Samsung TV Plus IT",
        "url": "https://i.mjh.nz/SamsungTVPlus/it.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-it",
        "label": "Pluto TV — Italy",
        "region": "IT",
        "name": "Pluto TV IT",
        "url": "https://i.mjh.nz/PlutoTV/it.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-br",
        "label": "Samsung TV Plus — Brazil",
        "region": "BR",
        "name": "Samsung TV Plus BR",
        "url": "https://i.mjh.nz/SamsungTVPlus/br.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "pluto-br",
        "label": "Pluto TV — Brazil",
        "region": "BR",
        "name": "Pluto TV BR",
        "url": "https://i.mjh.nz/PlutoTV/br.m3u8",
        "group": "Pluto TV",
    },
    {
        "id": "samsung-au",
        "label": "Samsung TV Plus — Australia",
        "region": "AU",
        "name": "Samsung TV Plus AU",
        "url": "https://i.mjh.nz/SamsungTVPlus/au.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        "id": "samsung-mx",
        "label": "Samsung TV Plus — Mexico",
        "region": "MX",
        "name": "Samsung TV Plus MX",
        "url": "https://i.mjh.nz/SamsungTVPlus/mx.m3u8",
        "group": "Samsung TV Plus",
    },
    {
        # Not on Samsung/Pluto — community streams via iptv-org. These have no
        # embedded guide, so EPG coverage is sparse; streams can be flaky.
        "id": "jamaica",
        "label": "Jamaica (iptv-org)",
        "region": "JM",
        "name": "Jamaica",
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
