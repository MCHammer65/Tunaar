# Tunaar licensing webhook

A tiny owner-side service that turns **Lemon Squeezy** purchases into signed
Tunaar license keys and emails them to buyers. It is **not** part of the Tunaar
container and never ships to customers — only you run it, and only it holds the
private key.

## How it works

```
Buyer → Lemon Squeezy checkout → webhook (this service)
        → verify signature → sign key (private key) → email key to buyer
```

Keys are Ed25519-signed tokens verified offline by every Tunaar install against
the matching **public** key (`TUNAAR_LICENSE_PUBKEY`).

## One-time setup

1. **Generate your keypair** (keep PRIVATE secret):
   ```sh
   python scripts/sign_license.py gen
   ```
   - Set `TUNAAR_LICENSE_PUBKEY=<public hex>` on every **Tunaar** container.
   - Set `TUNAAR_LICENSE_PRIVKEY=<private hex>` on **this webhook** only.

2. **Create products in Lemon Squeezy**: a `$20/yr` subscription and a `$50`
   one-off "lifetime". Note the **lifetime variant id**.

3. **Add a webhook** in Lemon Squeezy → Settings → Webhooks:
   - URL: `https://your-host/webhook`
   - Events: `order_created`, `subscription_payment_success`
   - Copy the **signing secret**.

## Configuration (environment variables)

| Variable | Required | Purpose |
|---|---|---|
| `TUNAAR_LICENSE_PRIVKEY` | ✅ | Ed25519 private seed (hex) used to sign keys |
| `LS_WEBHOOK_SECRET` | ✅¹ | Lemon Squeezy webhook signing secret |
| `LS_VARIANT_LIFETIME` | – | Variant id that means "lifetime" (else name contains "lifetime") |
| `STRIPE_WEBHOOK_SECRET` | ✅² | Stripe endpoint signing secret (`whsec_…`) |
| `STRIPE_LIFETIME_AMOUNT` | – | `amount_total` in minor units that means "lifetime" (else set `metadata.plan`) |
| `TUNAAR_ANNUAL_DAYS` | – | Annual length in days (default 365) |
| `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`/`SMTP_FROM` | – | Email out; if unset, keys are logged |

¹ Required only if you use Lemon Squeezy (`/webhook`). ² Required only if you
use Stripe (`/stripe-webhook`). You can run either or both.

## Using Stripe instead of (or alongside) Lemon Squeezy

Stripe acquired Lemon Squeezy, but they serve different needs: **Lemon Squeezy
is a Merchant of Record** (it handles your VAT/sales tax), whereas with **raw
Stripe you are the merchant of record** and must register for and remit tax
yourself. For a small company selling worldwide, Lemon Squeezy is usually less
admin.

To use Stripe: create two Products/Prices (annual subscription + one-off
lifetime), add a webhook for **`checkout.session.completed`** pointing at
`https://your-host/stripe-webhook`, set `STRIPE_WEBHOOK_SECRET`, and either set
`STRIPE_LIFETIME_AMOUNT` (the lifetime price in pence/cents) or pass
`metadata.plan = "lifetime"` when creating the checkout. The handler signs and
emails a key exactly like the Lemon Squeezy path.

## Run

```sh
pip install -r licensing-server/requirements.txt
TUNAAR_LICENSE_PRIVKEY=... LS_WEBHOOK_SECRET=... python licensing-server/webhook.py
```

Or with Docker (build from the repo root so the `tunaar` package is included):

```sh
docker build -f licensing-server/Dockerfile -t tunaar-webhook .
docker run -d -p 8080:8080 \
  -e TUNAAR_LICENSE_PRIVKEY=... -e LS_WEBHOOK_SECRET=... \
  -e SMTP_HOST=... -e SMTP_USER=... -e SMTP_PASS=... -e SMTP_FROM=you@domain \
  tunaar-webhook
```

Host it anywhere that runs a container (Fly.io, Render, a VPS). Put it behind
HTTPS — Lemon Squeezy only posts to https URLs.

## Manual key issue (no webhook)

You can always mint a key by hand:

```sh
python scripts/sign_license.py sign --priv <hex> --email a@b.com --plan annual --days 365
python scripts/sign_license.py sign --priv <hex> --email a@b.com --plan lifetime
```

## Security notes

- The **private key only lives on this service**. If it leaks, rotate it
  (new keypair) and ship a new public key in the next Tunaar release.
- The webhook rejects any request whose `X-Signature` doesn't match
  `LS_WEBHOOK_SECRET`, so only Lemon Squeezy can mint keys.
