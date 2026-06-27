# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal pure-Python Ed25519 (RFC 8032), vendored to avoid a native dep.

Used only for license signing/verification, which isn't performance-critical.
Based on the public-domain reference implementation by D. J. Bernstein et al.
Keys are standard 32-byte seeds / 32-byte public keys, so tokens are compatible
with any standard Ed25519 tooling.
"""

from __future__ import annotations

import hashlib
import os

_b = 256
_q = 2 ** 255 - 19
_l = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x: int) -> int:
    return pow(x, _q - 2, _q)


_d = (-121665 * _inv(121666)) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = 4 * _inv(5) % _q
_Bx = _xrecover(_By)
_B = [_Bx % _q, _By % _q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return [x3 % _q, y3 % _q]


def _scalarmult(P, e):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _encodeint(y: int) -> bytes:
    return y.to_bytes(_b // 8, "little")


def _encodepoint(P) -> bytes:
    x, y = P
    bits = [(y >> i) & 1 for i in range(_b - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8))


def _decodeint(s: bytes) -> int:
    return sum(2 ** i * _bit(s, i) for i in range(0, _b))


def _decodepoint(s: bytes):
    y = sum(2 ** i * _bit(s, i) for i in range(0, _b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    P = [x, y]
    if (-x * x + y * y - 1 - _d * x * x * y * y) % _q != 0:
        raise ValueError("point not on curve")
    return P


def _hint(m: bytes) -> int:
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * _b))


def _secret_scalar(h: bytes) -> int:
    return 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))


def publickey(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret seed."""
    h = _H(seed)
    A = _scalarmult(_B, _secret_scalar(h))
    return _encodepoint(A)


def sign(message: bytes, seed: bytes) -> bytes:
    """Return the 64-byte signature of ``message`` under secret ``seed``."""
    h = _H(seed)
    a = _secret_scalar(h)
    pk = _encodepoint(_scalarmult(_B, a))
    r = _hint(h[_b // 8:_b // 4] + message)
    R = _scalarmult(_B, r)
    S = (r + _hint(_encodepoint(R) + pk + message) * a) % _l
    return _encodepoint(R) + _encodeint(S)


def verify(signature: bytes, message: bytes, public_key: bytes) -> bool:
    """Return True iff ``signature`` is valid for ``message`` and ``public_key``."""
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        R = _decodepoint(signature[:32])
        A = _decodepoint(public_key)
        S = _decodeint(signature[32:])
        h = _hint(signature[:32] + public_key + message)
        return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
    except (ValueError, IndexError):
        return False


def keygen() -> tuple[bytes, bytes]:
    """Generate a new (seed, public_key) pair."""
    seed = os.urandom(32)
    return seed, publickey(seed)
