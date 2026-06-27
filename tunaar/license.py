# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline license verification and trial tracking.

Tunaar is self-hosted, so licensing is honour-based: the goal is to make paying
easier than patching, not to build unbreakable DRM. Licenses are **Ed25519
signed tokens** verified entirely offline against an embedded public key — no
phone-home, which suits locked-down NAS networks and respects privacy.

A license key is two base64url parts joined by a dot:

    <base64url(payload_json)>.<base64url(signature)>

``payload`` is ``{"email", "plan", "exp"}`` where ``plan`` is ``"annual"`` or
``"lifetime"`` and ``exp`` is a unix timestamp (0/absent = never expires). The
signature covers the raw payload bytes.

The owner generates a keypair once (``scripts/sign_license.py gen``), keeps the
private key secret to sign purchases, and ships the public key — either baked
into ``PUBLIC_KEY_HEX`` below or via the ``TUNAAR_LICENSE_PUBKEY`` env var.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from datetime import datetime

import requests

from . import _ed25519

# Lemon Squeezy license validation (Option B — no self-hosted key server).
LS_VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"
LS_ACTIVATE_URL = "https://api.lemonsqueezy.com/v1/licenses/activate"
NET_GRACE_DAYS = 14  # keep a known-good license if Lemon Squeezy is unreachable

# Replace with your real public key (hex) for production, or set
# TUNAAR_LICENSE_PUBKEY. Empty means "no valid licenses" — trial only.
PUBLIC_KEY_HEX = ""

TRIAL_DAYS = 30
GRACE_DAYS = 14  # keep an expired annual license working briefly during renewal
DAY = 86400

# Verification is pure-Python (a few ms) but evaluate() runs on every status
# poll, so cache results keyed on (key, pubkey).
_verify_cache: dict = {}


def _public_key_hex() -> str:
    return (os.environ.get("TUNAAR_LICENSE_PUBKEY") or PUBLIC_KEY_HEX or "").strip()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_key(
    private_key_hex: str,
    email: str,
    plan: str = "annual",
    days: int = 365,
    now: float | None = None,
) -> str:
    """Sign and return a license key (owner-side; needs the private key).

    ``plan`` is ``"annual"`` (expires after ``days``) or ``"lifetime"`` (never).
    The output is verifiable by :func:`verify_key` with the matching public key.
    """
    seed = binascii.unhexlify(private_key_hex)
    now = time.time() if now is None else now
    exp = 0 if plan == "lifetime" else int(now) + days * DAY
    payload = {"email": email, "plan": plan, "exp": exp}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = _ed25519.sign(raw, seed)
    return f"{_b64url_encode(raw)}.{_b64url_encode(sig)}"


def verify_key(key: str, public_key_hex: str | None = None) -> dict | None:
    """Return the payload dict if ``key`` is validly signed, else ``None``."""
    pub_hex = public_key_hex if public_key_hex is not None else _public_key_hex()
    if not pub_hex or not key or "." not in key:
        return None
    cache_key = (key, pub_hex)
    if cache_key in _verify_cache:
        return _verify_cache[cache_key]
    result = None
    try:
        payload_b64, sig_b64 = key.strip().split(".", 1)
        payload_raw = _b64url_decode(payload_b64)
        signature = _b64url_decode(sig_b64)
        public_key = binascii.unhexlify(pub_hex)
        if _ed25519.verify(signature, payload_raw, public_key):
            result = json.loads(payload_raw)
    except (ValueError, binascii.Error, json.JSONDecodeError):
        result = None
    _verify_cache[cache_key] = result
    return result


def _parse_expiry(value: str | None) -> float | None:
    """Parse a Lemon Squeezy ISO-8601 ``expires_at`` to epoch seconds, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _normalize(data: dict, ok_key: str) -> dict:
    """Shape a Lemon Squeezy activate/validate response into our state dict."""
    lk = data.get("license_key") or {}
    meta = data.get("meta") or {}
    inst = data.get("instance") or {}
    exp = _parse_expiry(lk.get("expires_at"))
    return {
        "reachable": True,
        "valid": bool(data.get(ok_key)) and lk.get("status") != "disabled",
        "status": lk.get("status", ""),
        "error": data.get("error"),
        "instance_id": inst.get("id", ""),
        "email": meta.get("customer_email", ""),
        "plan": "lifetime" if exp is None else "annual",
        "expires_at": exp,
    }


def validate_ls(license_key: str, instance_id: str = "", *, timeout: int = 10) -> dict:
    """Validate a Lemon Squeezy license key (optionally a specific activation).

    Returns a normalized dict. ``reachable`` is False on any network/HTTP error
    so the caller can apply a grace window; otherwise ``valid`` reflects whether
    Lemon Squeezy accepts the key (and this ``instance_id``, when given).
    """
    body = {"license_key": license_key}
    if instance_id:
        body["instance_id"] = instance_id
    try:
        resp = requests.post(LS_VALIDATE_URL, data=body,
                             headers={"Accept": "application/json"}, timeout=timeout)
        data = resp.json()
    except Exception:  # noqa: BLE001 - any failure means "couldn't check"
        return {"reachable": False}
    return _normalize(data, "valid")


def activate_ls(license_key: str, instance_name: str, *, timeout: int = 10) -> dict:
    """Activate a Lemon Squeezy license key for this install (consumes one of the
    key's activations). On success ``instance_id`` identifies this device; if the
    activation limit is reached, ``valid`` is False and ``error`` explains why.
    """
    try:
        resp = requests.post(
            LS_ACTIVATE_URL,
            data={"license_key": license_key, "instance_name": instance_name},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        data = resp.json()
    except Exception:  # noqa: BLE001
        return {"reachable": False}
    return _normalize(data, "activated")


def trial_state(trial_start: float, now: float) -> dict:
    """The (offline) trial/expired state when there's no valid license."""
    trial_end = (trial_start or now) + TRIAL_DAYS * DAY
    if now < trial_end:
        return {"state": "trial", "plan": "trial", "email": "",
                "days_left": max(0, int((trial_end - now) / DAY)), "premium": True}
    return {"state": "expired", "plan": "expired", "email": "",
            "days_left": 0, "premium": False}


def evaluate(ls_result: dict | None, trial_start: float, now: float | None = None) -> dict:
    """Compute the current license state from a (cached) Lemon Squeezy result.

    ``ls_result`` is the dict from :func:`validate_ls` (or None when there's no
    key). A valid result yields a ``licensed`` state; otherwise we fall back to
    the offline trial window.
    """
    now = time.time() if now is None else now
    if ls_result and ls_result.get("valid"):
        exp = ls_result.get("expires_at")
        return {
            "state": "licensed",
            "plan": ls_result.get("plan", "licensed"),
            "email": ls_result.get("email", ""),
            "days_left": None if exp is None else max(0, int((exp - now) / DAY)),
            "premium": True,
        }
    return trial_state(trial_start, now)
