# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""License validation and trial tracking.

Licenses are validated against the Lemon Squeezy licensing API. A short network
grace window keeps a known-good license working through a brief outage, and a
30-day offline trial covers first-run use before any key is entered. The goal is
to make paying easier than patching, not to build unbreakable DRM.
"""

from __future__ import annotations

import time
from datetime import datetime

import requests

# Lemon Squeezy license validation.
LS_VALIDATE_URL = "https://api.lemonsqueezy.com/v1/licenses/validate"
LS_ACTIVATE_URL = "https://api.lemonsqueezy.com/v1/licenses/activate"
NET_GRACE_DAYS = 14  # keep a known-good license if Lemon Squeezy is unreachable

TRIAL_DAYS = 30
RENEWAL_GRACE_DAYS = 14  # an expired annual key keeps full features during renewal
DAY = 86400

# Basic tier (what keeps working once entitlement lapses and enforcement is on).
# The bridge still runs, but capped — premium reliability features are off.
BASIC_MAX_SOURCES = 1
BASIC_MAX_CHANNELS = 100


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
    """The (offline) trial/expired state when there's no valid license.

    ``premium`` reflects raw entitlement (True only while the trial is live);
    enforcement (whether a lapse actually locks features) is applied later in
    :func:`evaluate`.
    """
    trial_end = (trial_start or now) + TRIAL_DAYS * DAY
    if now < trial_end:
        return {"state": "trial", "plan": "trial", "email": "",
                "days_left": max(0, int((trial_end - now) / DAY)),
                "premium": True, "nag": False, "expires_at": trial_end}
    return {"state": "expired", "plan": "trial", "email": "",
            "days_left": 0, "premium": False, "nag": True, "expires_at": trial_end}


def _entitlement(ls_result: dict | None, trial_start: float, now: float) -> dict:
    """Raw license/trial entitlement, before enforcement is applied.

    Order: a valid Lemon Squeezy key → ``licensed``; a key that merely *expired*
    → a 14-day ``grace`` window (full features, prompts to renew) then
    ``expired``; otherwise fall back to the offline trial window.
    """
    if ls_result and ls_result.get("valid"):
        exp = ls_result.get("expires_at")
        return {
            "state": "licensed",
            "plan": ls_result.get("plan", "licensed"),
            "email": ls_result.get("email", ""),
            "days_left": None if exp is None else max(0, int((exp - now) / DAY)),
            "premium": True, "nag": False, "expires_at": exp,
        }
    if ls_result and ls_result.get("expires_at"):
        exp = ls_result["expires_at"]
        if now < exp + RENEWAL_GRACE_DAYS * DAY:
            return {
                "state": "grace",
                "plan": "annual",
                "email": ls_result.get("email", ""),
                "days_left": max(0, int((exp + RENEWAL_GRACE_DAYS * DAY - now) / DAY)),
                "premium": True, "nag": True, "expires_at": exp,
            }
        return {"state": "expired", "plan": "expired",
                "email": ls_result.get("email", ""),
                "days_left": 0, "premium": False, "nag": True, "expires_at": exp}
    return trial_state(trial_start, now)


def evaluate(
    ls_result: dict | None,
    trial_start: float,
    now: float | None = None,
    *,
    enforce: str = "nag",
) -> dict:
    """Compute the current license state from a (cached) Lemon Squeezy result.

    ``ls_result`` is the dict from :func:`validate_ls` (or None when there's no
    key). ``premium`` is the raw entitlement; ``basic_locked`` is True only when
    entitlement has lapsed **and** ``enforce == "premium"`` — that's when the app
    drops to the capped basic tier. In the default ``"nag"`` mode features stay
    on and only a prompt is shown.
    """
    now = time.time() if now is None else now
    state = _entitlement(ls_result, trial_start, now)
    state["enforce"] = enforce
    state["basic_locked"] = (not state["premium"]) and (enforce == "premium")
    return state
