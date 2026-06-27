# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Targeted SSRF guard for outbound fetches.

Tunaar deliberately fetches LAN devices (a real HDHomeRun on 192.168.x.x) and
owner-supplied playlist/EPG URLs, so a blanket "block private IPs" policy would
break the product. This guard is narrow on purpose:

* Only ``http`` / ``https`` URLs are allowed (no ``file://``, ``gopher://`` …).
* Cloud-metadata / link-local addresses (169.254.0.0/16, fe80::/10) are blocked
  — that's the classic SSRF target.
* Private LAN ranges and loopback are explicitly **allowed** (HDHomeRun, local
  sidecars, VPN containers all live there).

Unresolvable hosts are passed through so the real fetch surfaces a normal DNS
error rather than a confusing "blocked" message.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")
BLOCKED_HOSTNAMES = {"metadata.google.internal"}


class BlockedURL(ValueError):
    """Raised when a URL is refused by the SSRF guard."""


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # Link-local covers 169.254.169.254 (AWS/GCP/Azure metadata) and fe80::/10.
    return ip.is_link_local


def check_url(url: str) -> None:
    """Raise :class:`BlockedURL` if ``url`` must not be fetched."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme not allowed: {scheme or '(none)'}")
    host = (parsed.hostname or "").strip()
    if not host:
        raise BlockedURL("missing host")
    if host.lower() in BLOCKED_HOSTNAMES:
        raise BlockedURL(f"blocked host: {host}")
    # A host given as an IP literal is checked directly; a name is resolved.
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except socket.gaierror:
            return  # let the actual request raise a normal DNS error
    for ip_str in candidates:
        if _is_blocked_ip(ip_str):
            raise BlockedURL(f"link-local/metadata address blocked: {ip_str}")
