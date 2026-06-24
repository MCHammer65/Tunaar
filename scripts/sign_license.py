#!/usr/bin/env python3
"""Generate keys and sign Tunaar license tokens (owner-side tool).

Usage:
  python scripts/sign_license.py gen
      → prints a new Ed25519 keypair. Keep PRIVATE secret; ship PUBLIC
        (set TUNAAR_LICENSE_PUBKEY or paste into tunaar/license.py).

  python scripts/sign_license.py sign --priv <hex> --email a@b.com \
      --plan annual --days 365
  python scripts/sign_license.py sign --priv <hex> --email a@b.com \
      --plan lifetime
      → prints a license key to give the customer.
"""

import argparse
import base64
import binascii
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tunaar import _ed25519  # noqa: E402


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def gen() -> None:
    seed, pub = _ed25519.keygen()
    print("PRIVATE (keep secret):", seed.hex())
    print("PUBLIC  (ship in app):", pub.hex())


def sign(args) -> None:
    seed = binascii.unhexlify(args.priv)
    exp = 0 if args.plan == "lifetime" else int(time.time()) + args.days * 86400
    payload = {"email": args.email, "plan": args.plan, "exp": exp}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = _ed25519.sign(raw, seed)
    print(f"{_b64url(raw)}.{_b64url(sig)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen")
    s = sub.add_parser("sign")
    s.add_argument("--priv", required=True)
    s.add_argument("--email", required=True)
    s.add_argument("--plan", choices=["annual", "lifetime"], default="annual")
    s.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    if args.cmd == "gen":
        gen()
    else:
        sign(args)


if __name__ == "__main__":
    main()
