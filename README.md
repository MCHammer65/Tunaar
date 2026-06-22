<div align="center">
  <img src="tunaar/static/logo.svg" width="96" alt="Tunaar logo">
  <h1>Tunaar</h1>
  <p><strong>IPTV for Plex that just works.</strong><br>
  A single-container HDHomeRun-emulating bridge that turns any IPTV M3U playlist
  into Live TV for Plex, Emby & Jellyfin — with XMLTV guide data and reliable,
  ffmpeg-remuxed streaming.</p>
</div>

---

## Why Tunaar?

Tools like xTeVe are powerful but notoriously clunky — fiddly UI, tedious EPG
mapping, buffering that drops streams, and config that corrupts. Tunaar focuses
on being **robust and effortless**:

- 🎯 **One Docker container.** `docker compose up` and you're done — ffmpeg
  included.
- 📡 **Real tuner slots.** Concurrent streams are capped at `tuner_count` and
  released the moment a client disconnects — no phantom "all tuners busy".
- 🎬 **Reliable streaming.** Each channel is remuxed through ffmpeg
  (`-c copy -f mpegts`, auto-reconnect) into a clean MPEG-TS that players accept
  without the hit-and-miss buffering of bare redirects. HLS sources just work.
- 🗓️ **EPG built in.** Point it at an XMLTV URL; Tunaar filters the guide to your
  lineup and serves it at `/epg.xml`.
- 🛡️ **Config that can't corrupt.** Written atomically and validated on load.
- 📊 **Clean dashboard.** Live status, channels, and active tuners at a glance.

## Quick start (Docker)

```bash
git clone https://github.com/MCHammer65/PlexIPTV.git tunaar && cd tunaar
mkdir -p config && cp config.example.json config/config.json
# edit config/config.json -> set "playlist" (and "epg_url" if you have one)
docker compose up -d
```

Open `http://<host>:5004` for the dashboard.

> `docker-compose.yml` uses `network_mode: host` so Plex can auto-discover the
> tuner on your LAN. Prefer port mapping? Comment that line out and uncomment the
> `ports:` block.

### Run without Docker

```bash
pip install -r requirements.txt
cp config.example.json config.json   # edit "playlist"
python run.py
```

ffmpeg must be on `PATH` for the default `ffmpeg` stream mode (Tunaar falls back
to direct passthrough if it isn't).

## Add the tuner in Plex

1. **Settings → Live TV & DVR → Set up Plex DVR.**
2. If it isn't auto-detected, enter the address manually, e.g. `192.168.1.50:5004`.
3. Map channels. For the guide, choose **"Have an XMLTV file?"** and point Plex at
   `http://192.168.1.50:5004/epg.xml` (or use Plex's own guide and let it match).

Emby/Jellyfin: add an **M3U Tuner** at `…/lineup.json` (or an HDHomeRun device)
and an **XMLTV** guide at `…/epg.xml`.

## Configuration

`config.json` (see `config.example.json`):

| Key | Description |
|-----|-------------|
| `friendly_name` | Tuner name shown in Plex. |
| `device_id` | Stable device id. Leave `""` to auto-generate & persist. |
| `tuner_count` | Max simultaneous streams (tuner slots). |
| `host` / `port` | Bind address (default `0.0.0.0:5004`). |
| `playlist` | **Required.** URL or path to your M3U playlist. |
| `epg_url` | URL or path to an XMLTV guide (`.xml` or `.xml.gz`). Optional. |
| `stream_mode` | `ffmpeg` (default, robust), `direct` (passthrough), or `redirect`. |
| `filter_epg_to_lineup` | Trim the guide to channels in your lineup (default `true`). |
| `user_agent` | User-Agent sent to playlist/EPG/stream sources. |
| `buffer_chunk` | Stream read size in bytes. |
| `playlist_refresh` / `epg_refresh` | Cache TTLs in seconds. |
| `advertised_url` | Override the base URL given to Plex (reverse-proxy setups). |

Config path: `TUNAAR_CONFIG` env var (defaults to `config.json`, `/config/config.json` in Docker).

## Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Branded status dashboard. |
| `GET /discover.json` · `/lineup.json` · `/lineup_status.json` · `/device.xml` | HDHomeRun emulation for Plex. |
| `POST /lineup.post` | Channel-scan trigger (no-op). |
| `GET /stream/<n>` | Remuxed/proxied stream for channel `n` (consumes a tuner slot). |
| `GET /epg.xml` | XMLTV guide, filtered to your lineup. |
| `GET /api/status` · `/api/channels` | JSON for the dashboard. |
| `GET /healthz` | Health check. |

## Development

```bash
pip install -r requirements.txt pytest
pytest
```

## Roadmap

- Editable channel ordering / filtering from the dashboard.
- SSDP broadcast for fully zero-config discovery.
- Per-source playlist merging and channel grouping.

## License

See [LICENSE](LICENSE).
