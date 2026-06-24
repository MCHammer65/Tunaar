"""Lemon Squeezy → Tunaar license webhook (owner-side service).

This is **not** part of the Tunaar container — it's a tiny service you host to
turn purchases into signed license keys. On a Lemon Squeezy order it:

1. verifies the request HMAC signature (``X-Signature``),
2. works out the plan (annual vs lifetime) from the variant,
3. signs a license key with your PRIVATE key (never shipped to customers), and
4. emails the key to the buyer (or logs it if SMTP isn't configured).

Configure with environment variables:

  TUNAAR_LICENSE_PRIVKEY   hex Ed25519 private seed (from sign_license.py gen)
  LS_WEBHOOK_SECRET        Lemon Squeezy webhook signing secret
  LS_VARIANT_LIFETIME      (optional) variant id that means "lifetime"
  TUNAAR_ANNUAL_DAYS       (optional) annual length in days, default 365

  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM
                           (optional) outbound email; if unset, keys are logged

Run:  python licensing-server/webhook.py   (serves on :8080 via waitress)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import smtplib
import sys
from email.message import EmailMessage

from flask import Flask, jsonify, request

# Reuse the canonical signer from the Tunaar package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tunaar import license as lic  # noqa: E402

log = logging.getLogger("tunaar-webhook")
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Events that grant/renew a license.
GRANT_EVENTS = {"order_created", "subscription_payment_success", "license_key_created"}


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def verify_signature(raw_body: bytes, header_sig: str) -> bool:
    secret = _env("LS_WEBHOOK_SECRET")
    if not secret:
        log.warning("LS_WEBHOOK_SECRET not set — rejecting webhook")
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, (header_sig or "").strip())


def extract_purchase(payload: dict) -> dict | None:
    """Pull the buyer email + variant out of a Lemon Squeezy payload."""
    attrs = (payload.get("data") or {}).get("attributes") or {}
    email = attrs.get("user_email") or attrs.get("customer_email") or ""
    item = attrs.get("first_order_item") or {}
    variant_id = str(item.get("variant_id") or attrs.get("variant_id") or "")
    variant_name = (item.get("variant_name") or attrs.get("variant_name") or "")
    if not email:
        return None
    return {"email": email, "variant_id": variant_id, "variant_name": variant_name}


def plan_for(purchase: dict) -> tuple[str, int]:
    """Return ``(plan, days)`` for a purchase."""
    lifetime_variant = _env("LS_VARIANT_LIFETIME")
    is_lifetime = (
        (lifetime_variant and purchase["variant_id"] == lifetime_variant)
        or "lifetime" in purchase["variant_name"].lower()
    )
    if is_lifetime:
        return "lifetime", 0
    return "annual", int(_env("TUNAAR_ANNUAL_DAYS", "365"))


def deliver(email: str, key: str, plan: str) -> None:
    """Email the license key, or log it if SMTP isn't configured."""
    host = _env("SMTP_HOST")
    if not host:
        log.info("Issued %s key for %s (SMTP not configured): %s", plan, email, key)
        return
    msg = EmailMessage()
    msg["Subject"] = "Your Tunaar license key"
    msg["From"] = _env("SMTP_FROM", _env("SMTP_USER"))
    msg["To"] = email
    msg.set_content(
        "Thanks for supporting Tunaar!\n\n"
        f"Plan: {plan}\n\nYour license key:\n\n{key}\n\n"
        "Activate it in the dashboard: Settings → License → paste the key → Activate.\n"
    )
    with smtplib.SMTP(host, int(_env("SMTP_PORT", "587"))) as s:
        s.starttls()
        user, pwd = _env("SMTP_USER"), _env("SMTP_PASS")
        if user:
            s.login(user, pwd)
        s.send_message(msg)
    log.info("Emailed %s key to %s", plan, email)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.post("/webhook")
def webhook():
    raw = request.get_data()
    if not verify_signature(raw, request.headers.get("X-Signature", "")):
        return jsonify({"error": "bad signature"}), 401

    payload = request.get_json(silent=True) or {}
    event = ((payload.get("meta") or {}).get("event_name") or "").strip()
    if event not in GRANT_EVENTS:
        return jsonify({"ok": True, "ignored": event}), 200

    purchase = extract_purchase(payload)
    if not purchase:
        log.warning("No email in %s payload; skipping", event)
        return jsonify({"ok": True, "skipped": "no email"}), 200

    priv = _env("TUNAAR_LICENSE_PRIVKEY")
    if not priv:
        log.error("TUNAAR_LICENSE_PRIVKEY not set — cannot sign keys")
        return jsonify({"error": "server not configured"}), 500

    plan, days = plan_for(purchase)
    key = lic.make_key(priv, purchase["email"], plan=plan, days=days)
    deliver(purchase["email"], key, plan)
    return jsonify({"ok": True, "plan": plan, "email": purchase["email"]}), 200


if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=int(_env("PORT", "8080")))
