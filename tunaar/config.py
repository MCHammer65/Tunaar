"""Configuration handling for Tunaar.

Config is loaded from a JSON file merged over sane defaults, validated, and
written back **atomically** (temp file + ``os.replace``) so a crash or a
concurrent reader can never observe a half-written, corrupt config — one of
the long-standing pain points with similar tools.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields

VALID_STREAM_MODES = ("ffmpeg", "direct", "redirect")

DEFAULTS: dict = {
    "friendly_name": "Tunaar",
    "device_id": "",  # auto-generated and persisted on first run
    "tuner_count": 4,
    "host": "0.0.0.0",
    "port": 5004,
    "playlist": "",
    "epg_url": "",
    "advertised_url": None,
    "stream_mode": "ffmpeg",  # ffmpeg | direct | redirect
    "user_agent": "Tunaar/0.2 (HDHomeRun)",
    "buffer_chunk": 65536,
    "playlist_refresh": 3600,  # seconds
    "epg_refresh": 3600,  # seconds
    "filter_epg_to_lineup": True,
    "ffmpeg_path": "ffmpeg",
}


@dataclass
class Config:
    friendly_name: str = DEFAULTS["friendly_name"]
    device_id: str = DEFAULTS["device_id"]
    tuner_count: int = DEFAULTS["tuner_count"]
    host: str = DEFAULTS["host"]
    port: int = DEFAULTS["port"]
    playlist: str = DEFAULTS["playlist"]
    epg_url: str = DEFAULTS["epg_url"]
    advertised_url: str | None = DEFAULTS["advertised_url"]
    stream_mode: str = DEFAULTS["stream_mode"]
    user_agent: str = DEFAULTS["user_agent"]
    buffer_chunk: int = DEFAULTS["buffer_chunk"]
    playlist_refresh: int = DEFAULTS["playlist_refresh"]
    epg_refresh: int = DEFAULTS["epg_refresh"]
    filter_epg_to_lineup: bool = DEFAULTS["filter_epg_to_lineup"]
    ffmpeg_path: str = DEFAULTS["ffmpeg_path"]

    path: str = field(default="config.json", repr=False, compare=False)

    # -- loading / saving -------------------------------------------------

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or os.environ.get("TUNAAR_CONFIG", "config.json")
        data = dict(DEFAULTS)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data.update(json.load(fh))

        known = {f.name for f in fields(cls)} - {"path"}
        cfg = cls(**{k: v for k, v in data.items() if k in known}, path=path)
        cfg.validate()

        # Persist a generated device id so Plex sees a stable tuner identity.
        if not cfg.device_id:
            cfg.device_id = uuid.uuid4().hex[:8].upper()
            try:
                cfg.save()
            except OSError:
                pass  # read-only config dir is fine; id stays for this run
        return cfg

    def validate(self) -> None:
        if self.stream_mode not in VALID_STREAM_MODES:
            raise ValueError(
                f"stream_mode must be one of {VALID_STREAM_MODES}, "
                f"got {self.stream_mode!r}"
            )
        self.tuner_count = max(1, int(self.tuner_count))
        self.port = int(self.port)
        self.buffer_chunk = max(4096, int(self.buffer_chunk))

    def save(self) -> None:
        """Write the config atomically to avoid partial/corrupt files."""
        data = {k: v for k, v in asdict(self).items() if k != "path"}
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def public_dict(self) -> dict:
        """Config view safe to expose on the dashboard API."""
        data = {k: v for k, v in asdict(self).items() if k != "path"}
        return data
