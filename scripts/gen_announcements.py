#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Muneris Management Ltd
"""Generate ready-to-post release announcements from CHANGELOG.md.

Produces platform-specific drafts (Reddit, Hacker News, X/Mastodon, Discord) for
a given version. The release GitHub Action runs this and uploads the drafts as
artifacts — a human reviews and posts (forums punish bots; authenticity matters).
Owned channels (Discord/Mastodon) are auto-posted when their secrets are set.

Usage:
    python scripts/gen_announcements.py --version 0.11.0 \
        --repo MCHammer65/PlexIPTV --outdir dist/announcements
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = os.environ.get("ANNOUNCE_PRODUCT", "Tunaar")
TAGLINE = os.environ.get(
    "ANNOUNCE_TAGLINE",
    "a single-container IPTV & HDHomeRun bridge for Plex, Emby and Jellyfin.",
)


def extract_section(changelog: str, version: str) -> str:
    """Return the body of the [version] section of a Keep-a-Changelog file."""
    pattern = re.compile(
        r"^##\s*\[" + re.escape(version) + r"\].*?$(.*?)(?=^##\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(changelog)
    return m.group(1).strip() if m else ""


def bullet_lines(section: str) -> list[str]:
    """Flatten the '- ' bullets from a changelog section (drop ### headers)."""
    out: list[str] = []
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s and not s.startswith("#") and out:
            out[-1] += " " + s
    return [re.sub(r"\s+", " ", b).strip() for b in out]


def reddit_post(version: str, repo: str, bullets: list[str]) -> str:
    body = "\n".join(f"- {b}" for b in bullets)
    return f"""**{PRODUCT} {version} is out — {TAGLINE}**

Hey r/selfhosted! {PRODUCT} turns IPTV playlists and a real HDHomeRun into one
Live TV tuner your media server can use, with a unified XMLTV guide.

**What's new in {version}:**
{body}

Works with Plex, Jellyfin and Emby; runs as one Docker container with a 30-day
free trial.

Repo (AGPL-3.0): https://github.com/{repo}

Honest feedback very welcome — what would make this genuinely useful for your
setup?
"""


def hn_post(version: str, repo: str, bullets: list[str]) -> str:
    body = "\n".join(f"- {b}" for b in bullets)
    return f"""Show HN: {PRODUCT} {version} – IPTV + HDHomeRun bridge for Plex/Jellyfin/Emby

{TAGLINE}

What's new in {version}:
{body}

AGPL-3.0. Runs as one Docker container.

https://github.com/{repo}

I'd love feedback on the architecture and where it'd be most useful.
"""


def short_post(version: str, repo: str, bullets: list[str], limit: int) -> str:
    head = f"{PRODUCT} {version} is out 🎉 "
    tail = f" https://github.com/{repo}"
    room = limit - len(head) - len(tail)
    highlights = "; ".join(bullets)[:max(0, room)].rstrip("; ")
    return f"{head}{highlights}{tail}"


def discord_post(version: str, repo: str, bullets: list[str]) -> str:
    body = "\n".join(f"• {b}" for b in bullets)
    return (f"**{PRODUCT} {version} released** 🎉\n{TAGLINE}\n\n{body}\n\n"
            f"<https://github.com/{repo}>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="e.g. 0.11.0 or Unreleased")
    ap.add_argument("--repo", default="MCHammer65/PlexIPTV")
    ap.add_argument("--outdir", default="dist/announcements")
    ap.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    args = ap.parse_args()

    version = args.version.lstrip("v")
    changelog = Path(args.changelog).read_text(encoding="utf-8")
    section = extract_section(changelog, version)
    if not section:
        print(f"No changelog section found for [{version}]", file=sys.stderr)
        return 1
    bullets = bullet_lines(section)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    drafts = {
        "reddit.md": reddit_post(version, args.repo, bullets),
        "hackernews.txt": hn_post(version, args.repo, bullets),
        "twitter.txt": short_post(version, args.repo, bullets, 270),
        "mastodon.txt": short_post(version, args.repo, bullets, 490),
        "discord.txt": discord_post(version, args.repo, bullets),
        "release-notes.md": section,
    }
    for name, content in drafts.items():
        (outdir / name).write_text(content.rstrip() + "\n", encoding="utf-8")
        print(f"wrote {outdir / name}")

    # Optional: auto-post to OWNED channels (never to forums — those stay drafts).
    _post_discord(version, args.repo, bullets)
    _post_mastodon(version, args.repo, bullets)
    return 0


def _post_discord(version, repo, bullets) -> None:
    webhook = os.environ.get("ANNOUNCE_DISCORD_WEBHOOK", "").strip()
    if not webhook:
        return
    try:
        import json
        import urllib.request
        data = json.dumps({"content": discord_post(version, repo, bullets)}).encode()
        req = urllib.request.Request(
            webhook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)  # noqa: S310 (fixed webhook)
        print("posted announcement to Discord")
    except Exception as exc:  # best-effort
        print(f"Discord post failed: {exc}", file=sys.stderr)


def _post_mastodon(version, repo, bullets) -> None:
    instance = os.environ.get("ANNOUNCE_MASTODON_INSTANCE", "").strip().rstrip("/")
    token = os.environ.get("ANNOUNCE_MASTODON_TOKEN", "").strip()
    if not (instance and token):
        return
    try:
        import json
        import urllib.request
        status = short_post(version, repo, bullets, 480)
        data = json.dumps({"status": status}).encode()
        req = urllib.request.Request(
            f"{instance}/api/v1/statuses", data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        urllib.request.urlopen(req, timeout=15)  # noqa: S310 (owned instance)
        print("posted announcement to Mastodon")
    except Exception as exc:  # best-effort
        print(f"Mastodon post failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
