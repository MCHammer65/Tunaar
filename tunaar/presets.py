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
]


def get(preset_id: str) -> dict | None:
    """Return the preset with ``id == preset_id``, or ``None``."""
    for p in PRESETS:
        if p["id"] == preset_id:
            return p
    return None
