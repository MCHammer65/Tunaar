# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the targeted SSRF guard."""

import pytest

from tunaar import netguard


def test_allows_lan_and_loopback():
    # LAN (HDHomeRun lives here) and loopback (sidecars) must pass.
    netguard.check_url("http://192.168.1.50/lineup.json")
    netguard.check_url("http://10.0.0.5:5004/x")
    netguard.check_url("http://127.0.0.1:8080/playlist.m3u")
    netguard.check_url("https://iptv-org.github.io/iptv/index.m3u")


def test_blocks_cloud_metadata():
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("http://metadata.google.internal/")


def test_blocks_non_http_schemes():
    for bad in ("file:///etc/passwd", "gopher://x/", "ftp://h/f"):
        with pytest.raises(netguard.BlockedURL):
            netguard.check_url(bad)


def test_blocks_missing_host():
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("http://")


def test_unresolvable_host_passes_through():
    # DNS failure is left to the real fetch, not pre-emptively blocked.
    netguard.check_url("http://nonexistent.invalid.tld.example/x")
