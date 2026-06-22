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
- 🗓️ **EPG that just works.** Tunaar auto-detects the guide URL embedded in your
  playlist (`url-tvg`) and merges in any extra XMLTV URLs you add — no manual
  channel mapping. Filtered to your lineup and served at `/epg.xml`.
- ➕ **Multiple IPTV sources.** Add as many M3U playlists as you like (from the
  dashboard or config); channels are merged with collision-free numbering.
- 🗂️ **Group control.** Pick which groups appear in Plex from a checklist;
  per-source group overrides supported.
- 🖥️ **Editable dashboard.** Add sources, set EPG URLs, and choose groups right
  in the web UI — changes persist to config, no SSH required.
- 🔎 **Auto-discovery.** Answers HDHomeRun discovery (UDP 65001) so Plex finds
  the tuner automatically — no manual IP entry.
- 🛡️ **Config that can't corrupt.** Written atomically and validated on load.

## Quick start (Docker)

A pre-built multi-arch image (amd64 + arm64) is published to GHCR on every push
to `main`: **`ghcr.io/mchammer65/plexiptv:latest`**.

**No config file needed** — everything can be set with `TUNAAR_*` environment
variables. The only one you must set is your playlist:

```bash
docker run -d --name tunaar --restart unless-stopped \
  --network host \
  -e TUNAAR_PLAYLIST="https://iptv-org.github.io/iptv/index.m3u" \
  -v tunaar-config:/config \
  ghcr.io/mchammer65/plexiptv:latest
```

Open `http://<host>:5004` for the dashboard. That's it.

> Host networking keeps the advertised stream URLs correct on your LAN. On
> Docker Desktop (Mac/Windows), drop `--network host` and add `-p 5004:5004`.

### QNAP (Container Station)

QNAP NAS are Linux, so the pre-built image and host networking both work. The
one-liner above works over SSH (Container Station ships Docker). Or use the UI:

**Container Station → Containers → Create**, search the registry for
`ghcr.io/mchammer65/plexiptv`, choose **Host** networking, add an environment
variable `TUNAAR_PLAYLIST=<your playlist URL>`, and create.

> The GHCR package must be **public** (GitHub → Packages → plexiptv → Package
> settings → Change visibility) for the NAS to pull it without credentials.

Then browse to `http://<nas-ip>:5004`.

### Helper script (install / update / status)

`tunaar.sh` wraps the Docker commands so you don't have to remember the flags —
handy on a NAS over SSH:

```bash
TUNAAR_PLAYLIST="https://your/playlist.m3u" ./tunaar.sh up   # pull + start
./tunaar.sh update     # pull latest image, recreate, prune the old one
./tunaar.sh status     # container state + health check
./tunaar.sh logs       # follow logs
./tunaar.sh restart    # restart
./tunaar.sh down       # stop and remove
```

It reads `TUNAAR_PLAYLIST`, `TUNAAR_EPG_URL`, `TUNAAR_PORT`, `TUNAAR_IMAGE`,
`TUNAAR_VOLUME`, and `TUNAAR_NETWORK` (`host` or `bridge`) from the environment.

### Using a compose file instead

```bash
git clone https://github.com/MCHammer65/PlexIPTV.git tunaar && cd tunaar
# edit TUNAAR_PLAYLIST in docker-compose.yml
docker compose up -d
```

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
2. Tunaar answers HDHomeRun discovery (UDP 65001), so it should appear
   automatically. If it doesn't (e.g. Plex is on another subnet), click
   **"Enter its network address manually"** and enter `192.168.1.50:5004`.
3. Map channels. For the guide, choose **"Have an XMLTV file?"** and point Plex at
   `http://192.168.1.50:5004/epg.xml` (or use Plex's own guide and let it match).

> Auto-discovery needs the container on **host networking** (the default) so the
> broadcast reaches it. Disable it with `TUNAAR_DISCOVERY=false` if needed.

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

Every key can also be set via an environment variable named `TUNAAR_<KEY>` in
uppercase (e.g. `TUNAAR_PLAYLIST`, `TUNAAR_TUNER_COUNT`, `TUNAAR_EPG_URL`). Env
vars override the config file, so no file is required at all. The config file
path itself is set with `TUNAAR_CONFIG` (defaults to `config.json`, or
`/config/config.json` in Docker).

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
