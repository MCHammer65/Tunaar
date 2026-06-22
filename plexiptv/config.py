"""Configuration loading for PlexIPTV."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULTS = {
    "friendly_name": "PlexIPTV",
    "device_id": "12345678",
    "tuner_count": 2,
    "host": "0.0.0.0",
    "port": 5004,
    "playlist": "",
    "advertised_url": None,
}


@dataclass
class Config:
    friendly_name: str
    device_id: str
    tuner_count: int
    host: str
    port: int
    playlist: str
    advertised_url: str | None

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Load configuration from a JSON file, merged over the defaults.

        The config path can be given explicitly, via the ``PLEXIPTV_CONFIG``
        environment variable, or it falls back to ``config.json`` in the
        current working directory.
        """
        path = path or os.environ.get("PLEXIPTV_CONFIG", "config.json")
        data = dict(DEFAULTS)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data.update(json.load(fh))
        if not data["playlist"]:
            raise ValueError(
                f"No 'playlist' configured. Set it in {path} "
                "(see config.example.json)."
            )
        return cls(
            friendly_name=str(data["friendly_name"]),
            device_id=str(data["device_id"]),
            tuner_count=int(data["tuner_count"]),
            host=str(data["host"]),
            port=int(data["port"]),
            playlist=str(data["playlist"]),
            advertised_url=data["advertised_url"],
        )
