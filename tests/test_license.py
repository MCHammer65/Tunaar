"""Tests for offline license verification and trial logic."""

import base64
import json

from tunaar import _ed25519
from tunaar import license as lic


def _keypair():
    seed, pub = _ed25519.keygen()
    return seed, pub.hex()


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _make_key(seed, **payload) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64url(raw)}.{_b64url(_ed25519.sign(raw, seed))}"


def test_verify_valid_and_tampered(monkeypatch):
    priv, pub = _keypair()
    monkeypatch.setattr(lic, "PUBLIC_KEY_HEX", pub)
    key = _make_key(priv, email="a@b.com", plan="annual", exp=0)
    assert lic.verify_key(key)["email"] == "a@b.com"
    # Tamper with the payload → signature no longer matches.
    body, sig = key.split(".")
    bad = _b64url(b'{"email":"x","plan":"lifetime","exp":0}') + "." + sig
    assert lic.verify_key(bad) is None
    # Wrong public key rejects a genuine token.
    _, other = _keypair()
    assert lic.verify_key(key, public_key_hex=other) is None


def test_trial_window(monkeypatch):
    monkeypatch.setattr(lic, "PUBLIC_KEY_HEX", "")
    now = 1_000_000.0
    fresh = lic.evaluate("", now, now=now)
    assert fresh["state"] == "trial" and fresh["premium"] is True
    assert fresh["days_left"] == lic.TRIAL_DAYS
    expired = lic.evaluate("", now - 40 * lic.DAY, now=now)
    assert expired["state"] == "expired" and expired["premium"] is False


def test_licensed_overrides_expired_trial(monkeypatch):
    priv, pub = _keypair()
    monkeypatch.setattr(lic, "PUBLIC_KEY_HEX", pub)
    now = 2_000_000.0
    lifetime = _make_key(priv, email="a@b.com", plan="lifetime", exp=0)
    r = lic.evaluate(lifetime, now - 999 * lic.DAY, now=now)
    assert r["state"] == "licensed" and r["days_left"] is None  # never expires
    # Expired annual key falls back to (also expired) trial.
    annual = _make_key(priv, email="a@b.com", plan="annual", exp=int(now - lic.DAY))
    r2 = lic.evaluate(annual, now - 999 * lic.DAY, now=now)
    assert r2["state"] == "expired"
