# PlexIPTV

An **HDHomeRun tuner emulator** that exposes an IPTV **M3U playlist** to
**Plex Live TV & DVR**.

Plex can't ingest a raw M3U playlist directly — it talks to network tuners
that look like a [Silicondust HDHomeRun](https://www.silicondust.com/). PlexIPTV
pretends to be one of those tuners: it parses your M3U playlist and serves the
handful of HTTP endpoints Plex uses to discover the device and list channels.

## Features (MVP)

- Parses extended M3U / M3U8 playlists (`tvg-id`, `tvg-name`, `tvg-logo`,
  `group-title`, `tvg-chno`).
- Emulates the HDHomeRun discovery + lineup endpoints Plex expects.
- Redirects each channel to its real stream URL, with channel numbers taken
  from `tvg-chno` (or auto-assigned, collision-free).
- Caches the playlist so Plex's frequent polling doesn't refetch it every time.

## Quick start

```bash
pip install -r requirements.txt
cp config.example.json config.json   # then edit "playlist"
python run.py
```

By default the server listens on `0.0.0.0:5004`.

### Add the tuner in Plex

1. Open **Settings → Live TV & DVR → Set up Plex DVR**.
2. If the device isn't auto-detected, enter the server's address manually,
   e.g. `192.168.1.50:5004`.
3. Plex reads the lineup and walks you through channel mapping.

## Configuration

`config.json` (see `config.example.json`):

| Key              | Description                                                       |
|------------------|-------------------------------------------------------------------|
| `friendly_name`  | Name Plex shows for the tuner.                                     |
| `device_id`      | Unique device id reported to Plex.                                 |
| `tuner_count`    | Number of simultaneous tuners to advertise.                       |
| `host` / `port`  | Address the server binds to.                                       |
| `playlist`       | URL or local path to your M3U playlist. **Required.**             |
| `advertised_url` | Override the base URL given to Plex (useful behind a reverse proxy). |

The config path can also be set via the `PLEXIPTV_CONFIG` environment variable.

## Endpoints

| Endpoint              | Purpose                                            |
|-----------------------|----------------------------------------------------|
| `GET /discover.json`  | Device description Plex uses to identify the tuner. |
| `GET /lineup_status.json` | Scan / lineup status.                          |
| `GET /lineup.json`    | The channel lineup.                                |
| `POST /lineup.post`   | Channel-scan trigger (no-op).                      |
| `GET /device.xml`     | UPnP description (used by some discovery paths).   |
| `GET /stream/<n>`     | Redirects to the real stream for channel `n`.      |

## Tests

```bash
pip install pytest
pytest
```

## Roadmap

- XMLTV EPG handling and channel/EPG mapping helpers.
- A web UI to filter and reorder channels.
- SSDP broadcast for zero-config discovery.
- Stream proxying with real tuner-slot accounting.
