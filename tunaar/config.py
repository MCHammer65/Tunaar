"""Configuration handling for Tunaar.

Config is loaded from a JSON file merged over sane defaults, validated, and
written back **atomically** (temp file + ``os.replace``) so a crash or a
concurrent reader can never observe a half-written, corrupt config — one of
the long-standing pain points with similar tools.
"""

from __future__ import annotations

import json
import os
import re
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
    "playlist": "",  # legacy single source; folded into `sources` on load
    "sources": [],  # [{"name": str, "url": str, "group": optional override}]
    "epg_url": "",  # legacy; folded into `epg_urls` on load
    "epg_urls": [],  # extra XMLTV URLs, merged together
    "epg_auto": True,  # also use EPG URLs embedded in the playlist header
    "epg_overrides": {},  # manual channel-name -> guide tvg_id mappings
    "groups_include": [],  # if non-empty, only these groups are exposed
    "groups_exclude": [],  # these groups are always hidden
    "advertised_url": None,
    "stream_mode": "ffmpeg",  # ffmpeg | direct | redirect
    "user_agent": "Tunaar/0.2 (HDHomeRun)",
    "buffer_chunk": 65536,
    "playlist_refresh": 3600,  # seconds
    "epg_refresh": 3600,  # seconds
    "filter_epg_to_lineup": True,
    "ffmpeg_path": "ffmpeg",
    "discovery": True,  # answer HDHomeRun discovery so Plex auto-finds the tuner
    "discovery_port": 65001,
    "setup_complete": False,  # first-run wizard shown until dismissed/finished
}

# Managed as structured lists via the dashboard, not via env vars.
_ENV_SKIP = {"sources", "epg_urls", "epg_overrides"}


def _split_list(value: str) -> list[str]:
    """Split a comma/newline separated string into a clean list."""
    parts = re.split(r"[,\n]", value)
    return [p.strip() for p in parts if p.strip()]


def _coerce(default, raw: str):
    """Coerce an env-var string to the type of the matching default value."""
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, list):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


def _env_overrides(env: dict) -> dict:
    """Read TUNAAR_<FIELD> overrides for any known config key (except path)."""
    out: dict = {}
    for key, default in DEFAULTS.items():
        if key in _ENV_SKIP:
            continue
        raw = env.get(f"TUNAAR_{key.upper()}")
        if raw is not None and raw != "":
            out[key] = _coerce(default, raw)
    return out


@dataclass
class Config:
    friendly_name: str = DEFAULTS["friendly_name"]
    device_id: str = DEFAULTS["device_id"]
    tuner_count: int = DEFAULTS["tuner_count"]
    host: str = DEFAULTS["host"]
    port: int = DEFAULTS["port"]
    playlist: str = DEFAULTS["playlist"]
    sources: list = field(default_factory=list)
    epg_url: str = DEFAULTS["epg_url"]
    epg_urls: list = field(default_factory=list)
    epg_auto: bool = DEFAULTS["epg_auto"]
    epg_overrides: dict = field(default_factory=dict)
    groups_include: list = field(default_factory=list)
    groups_exclude: list = field(default_factory=list)
    advertised_url: str | None = DEFAULTS["advertised_url"]
    stream_mode: str = DEFAULTS["stream_mode"]
    user_agent: str = DEFAULTS["user_agent"]
    buffer_chunk: int = DEFAULTS["buffer_chunk"]
    playlist_refresh: int = DEFAULTS["playlist_refresh"]
    epg_refresh: int = DEFAULTS["epg_refresh"]
    filter_epg_to_lineup: bool = DEFAULTS["filter_epg_to_lineup"]
    ffmpeg_path: str = DEFAULTS["ffmpeg_path"]
    discovery: bool = DEFAULTS["discovery"]
    discovery_port: int = DEFAULTS["discovery_port"]
    setup_complete: bool = DEFAULTS["setup_complete"]

    path: str = field(default="config.json", repr=False, compare=False)

    # -- loading / saving -------------------------------------------------

    @classmethod
    def load(cls, path: str | None = None, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env
        path = path or env.get("TUNAAR_CONFIG", "config.json")
        data = dict(DEFAULTS)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data.update(json.load(fh))

        # Environment variables (TUNAAR_<FIELD>) override the file, so the whole
        # thing can be configured with no config file at all.
        data.update(_env_overrides(env))

        known = {f.name for f in fields(cls)} - {"path"}
        cfg = cls(**{k: v for k, v in data.items() if k in known}, path=path)
        cfg.normalize()
        cfg.validate()

        # Persist a generated device id so Plex sees a stable tuner identity.
        if not cfg.device_id:
            cfg.device_id = uuid.uuid4().hex[:8].upper()
            try:
                cfg.save()
            except OSError:
                pass  # read-only config dir is fine; id stays for this run
        return cfg

    def normalize(self) -> None:
        """Fold legacy single-value fields into the canonical list fields."""
        if not self.sources and self.playlist:
            self.sources = [
                {"name": "", "url": u}
                for u in _split_list(self.playlist)
            ]
        if not self.epg_urls and self.epg_url:
            self.epg_urls = _split_list(self.epg_url)

    def effective_epg_urls(self, discovered: list[str] | None = None) -> list[str]:
        """All EPG URLs to merge: configured ones plus, when ``epg_auto`` is on,
        any discovered from playlist headers."""
        urls = list(self.epg_urls)
        if self.epg_auto and discovered:
            urls.extend(discovered)
        seen: set[str] = set()
        return [u for u in urls if u and not (u in seen or seen.add(u))]

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
