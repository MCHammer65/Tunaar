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

from . import _ed25519

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


def evaluate(license_key: str, trial_start: float, now: float | None = None) -> dict:
    """Compute the current license state.

    Returns a dict with ``state`` (``licensed`` / ``trial`` / ``expired``),
    ``plan``, ``email``, ``days_left`` and ``premium`` (whether premium features
    should be enabled — true for trial and licensed).
    """
    now = time.time() if now is None else now
    payload = verify_key(license_key) if license_key else None

    if payload:
        exp = payload.get("exp") or 0
        if not exp or now < exp:
            days_left = None if not exp else max(0, int((exp - now) / DAY))
            return {
                "state": "licensed",
                "plan": payload.get("plan", "licensed"),
                "email": payload.get("email", ""),
                "days_left": days_left,
                "premium": True,
            }
        # Expired annual key: keep working through a short grace window so a
        # renewal that lands a little late doesn't interrupt the user.
        if now < exp + GRACE_DAYS * DAY:
            return {
                "state": "grace",
                "plan": payload.get("plan", "licensed"),
                "email": payload.get("email", ""),
                "days_left": max(0, int((exp + GRACE_DAYS * DAY - now) / DAY)),
                "premium": True,
            }
        # Fully expired: fall through to trial/expired below.

    trial_end = (trial_start or now) + TRIAL_DAYS * DAY
    if now < trial_end:
        return {
            "state": "trial",
            "plan": "trial",
            "email": "",
            "days_left": max(0, int((trial_end - now) / DAY)),
            "premium": True,
        }
    return {
        "state": "expired",
        "plan": "expired",
        "email": "",
        "days_left": 0,
        "premium": False,
    }
