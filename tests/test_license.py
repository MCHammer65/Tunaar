# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for Lemon Squeezy license validation and the offline trial window."""

from tunaar import license as lic


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _ls_response(valid=True, status="active", expires_at=None, email="a@b.com"):
    return {
        "valid": valid,
        "license_key": {"status": status, "expires_at": expires_at},
        "meta": {"customer_email": email},
    }


def test_trial_window():
    now = 1_000_000.0
    fresh = lic.trial_state(now, now)
    assert fresh["state"] == "trial" and fresh["premium"] is True
    assert fresh["days_left"] == lic.TRIAL_DAYS
    expired = lic.trial_state(now - 40 * lic.DAY, now)
    assert expired["state"] == "expired" and expired["premium"] is False


def test_validate_ls_valid_lifetime(monkeypatch):
    monkeypatch.setattr(lic.requests, "post", lambda *a, **k: _Resp(_ls_response()))
    res = lic.validate_ls("KEY")
    assert res["reachable"] and res["valid"]
    assert res["plan"] == "lifetime" and res["expires_at"] is None
    assert res["email"] == "a@b.com"


def test_activate_ls_success_and_limit(monkeypatch):
    monkeypatch.setattr(lic.requests, "post", lambda *a, **k: _Resp({
        "activated": True, "error": None,
        "license_key": {"status": "active", "expires_at": None},
        "instance": {"id": "inst-9"}, "meta": {"customer_email": "a@b.com"},
    }))
    res = lic.activate_ls("KEY", "My Device")
    assert res["valid"] and res["instance_id"] == "inst-9" and res["plan"] == "lifetime"
    # Activation limit reached → not valid, error surfaced.
    monkeypatch.setattr(lic.requests, "post", lambda *a, **k: _Resp({
        "activated": False, "error": "This license key has reached the activation limit.",
        "license_key": {"status": "active"}, "instance": None, "meta": {},
    }))
    res2 = lic.activate_ls("KEY", "Device 3")
    assert res2["valid"] is False and "activation limit" in res2["error"]


def test_validate_ls_annual_expiry(monkeypatch):
    monkeypatch.setattr(lic.requests, "post",
                        lambda *a, **k: _Resp(_ls_response(expires_at="2030-01-01T00:00:00Z")))
    res = lic.validate_ls("KEY")
    assert res["plan"] == "annual" and res["expires_at"] is not None


def test_validate_ls_invalid_and_unreachable(monkeypatch):
    monkeypatch.setattr(lic.requests, "post", lambda *a, **k: _Resp(_ls_response(valid=False, status="expired")))
    assert lic.validate_ls("KEY")["valid"] is False
    # Network error → not reachable (caller applies grace).
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(lic.requests, "post", boom)
    assert lic.validate_ls("KEY") == {"reachable": False}


def test_evaluate_licensed_overrides_expired_trial():
    now = 2_000_000.0
    licensed = {"reachable": True, "valid": True, "plan": "lifetime",
                "email": "a@b.com", "expires_at": None}
    out = lic.evaluate(licensed, now - 999 * lic.DAY, now=now)
    assert out["state"] == "licensed" and out["days_left"] is None
    # Invalid LS result with an expired trial → expired.
    out2 = lic.evaluate({"valid": False}, now - 999 * lic.DAY, now=now)
    assert out2["state"] == "expired" and out2["premium"] is False


def test_evaluate_annual_days_left():
    now = 2_000_000.0
    res = {"valid": True, "plan": "annual", "email": "a@b.com",
           "expires_at": now + 30 * lic.DAY}
    out = lic.evaluate(res, 0, now=now)
    assert out["state"] == "licensed" and out["days_left"] == 30
