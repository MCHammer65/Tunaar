# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Lemon Squeezy licensing webhook."""

import hashlib
import hmac
import json

import pytest

from tunaar import _ed25519, license as lic

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "tunaar_webhook",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "licensing-server", "webhook.py"),
)
webhook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(webhook)

SECRET = "whsec_test"


@pytest.fixture
def keys():
    seed, pub = _ed25519.keygen()
    return seed.hex(), pub.hex()


STRIPE_SECRET = "whsec_stripe_test"


@pytest.fixture
def client(keys, monkeypatch):
    priv, pub = keys
    monkeypatch.setenv("TUNAAR_LICENSE_PRIVKEY", priv)
    monkeypatch.setenv("LS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("LS_VARIANT_LIFETIME", "999")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", STRIPE_SECRET)
    monkeypatch.setenv("STRIPE_LIFETIME_AMOUNT", "5900")
    monkeypatch.setenv("TUNAAR_LICENSE_PUBKEY", pub)
    lic._verify_cache.clear()
    issued = []
    monkeypatch.setattr(webhook, "deliver", lambda email, key, plan: issued.append((email, key, plan)))
    c = webhook.app.test_client()
    c._issued = issued
    return c


def _post(client, payload, secret=SECRET):
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhook", data=raw, headers={"X-Signature": sig, "Content-Type": "application/json"})


def _order(email="buyer@example.com", variant_id="100", variant_name="Annual"):
    return {
        "meta": {"event_name": "order_created"},
        "data": {"attributes": {
            "user_email": email,
            "first_order_item": {"variant_id": variant_id, "variant_name": variant_name},
        }},
    }


def test_rejects_bad_signature(client):
    raw = json.dumps(_order()).encode()
    r = client.post("/webhook", data=raw, headers={"X-Signature": "deadbeef"})
    assert r.status_code == 401
    assert client._issued == []


def test_ignores_unrelated_events(client):
    r = _post(client, {"meta": {"event_name": "subscription_updated"}, "data": {}})
    assert r.status_code == 200 and r.get_json()["ignored"] == "subscription_updated"
    assert client._issued == []


def test_order_issues_annual_key_verifiable(client, keys):
    _priv, pub = keys
    r = _post(client, _order(variant_id="100", variant_name="Annual"))
    assert r.status_code == 200 and r.get_json()["plan"] == "annual"
    email, key, plan = client._issued[0]
    assert email == "buyer@example.com"
    payload = lic.verify_key(key, public_key_hex=pub)
    assert payload["plan"] == "annual" and payload["exp"] > 0


def test_lifetime_variant_issues_lifetime_key(client, keys):
    _priv, pub = keys
    r = _post(client, _order(variant_id="999", variant_name="Lifetime deal"))
    assert r.get_json()["plan"] == "lifetime"
    _email, key, _plan = client._issued[0]
    payload = lic.verify_key(key, public_key_hex=pub)
    assert payload["plan"] == "lifetime" and payload["exp"] == 0


def test_skips_when_no_email(client):
    r = _post(client, {"meta": {"event_name": "order_created"}, "data": {"attributes": {}}})
    assert r.status_code == 200 and "skipped" in r.get_json()
    assert client._issued == []


# ---- Stripe webhook ----

def _stripe_post(client, payload, secret=STRIPE_SECRET, t="1700000000"):
    raw = json.dumps(payload).encode()
    signed = t.encode() + b"." + raw
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return client.post(
        "/stripe-webhook", data=raw,
        headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"},
    )


def _session(email="buyer@example.com", amount=2000, plan=None):
    obj = {"customer_details": {"email": email}, "amount_total": amount, "metadata": {}}
    if plan:
        obj["metadata"]["plan"] = plan
    return {"type": "checkout.session.completed", "data": {"object": obj}}


def test_stripe_rejects_bad_signature(client):
    raw = json.dumps(_session()).encode()
    r = client.post("/stripe-webhook", data=raw, headers={"Stripe-Signature": "t=1,v1=bad"})
    assert r.status_code == 401
    assert client._issued == []


def test_stripe_checkout_issues_annual_by_default(client, keys):
    _priv, pub = keys
    r = _stripe_post(client, _session(amount=2000))  # not the lifetime amount
    assert r.get_json()["plan"] == "annual"
    _email, key, _plan = client._issued[0]
    assert lic.verify_key(key, public_key_hex=pub)["plan"] == "annual"


def test_stripe_lifetime_by_amount_and_metadata(client, keys):
    _priv, pub = keys
    # By configured lifetime amount (5900 set in fixture).
    r = _stripe_post(client, _session(amount=5900))
    assert r.get_json()["plan"] == "lifetime"
    # Or explicitly via metadata.
    client._issued.clear()
    r2 = _stripe_post(client, _session(amount=2000, plan="lifetime"))
    assert r2.get_json()["plan"] == "lifetime"
    assert lic.verify_key(client._issued[0][1], public_key_hex=pub)["exp"] == 0


def test_stripe_ignores_other_events(client):
    r = _stripe_post(client, {"type": "payment_intent.created", "data": {"object": {}}})
    assert r.status_code == 200 and r.get_json()["ignored"] == "payment_intent.created"
    assert client._issued == []
