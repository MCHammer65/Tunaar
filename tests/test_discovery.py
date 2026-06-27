# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the HDHomeRun discovery packet codec."""

import binascii
import struct

from tunaar import discovery as d


def _make_request() -> bytes:
    payload = (
        d._tlv(d.TAG_DEVICE_TYPE, struct.pack(">I", 0xFFFFFFFF))
        + d._tlv(d.TAG_DEVICE_ID, struct.pack(">I", 0xFFFFFFFF))
    )
    return d._packet(d.TYPE_DISCOVER_REQ, payload)


def _crc_ok(packet: bytes) -> bool:
    body, crc = packet[:-4], struct.unpack("<I", packet[-4:])[0]
    return (binascii.crc32(body) & 0xFFFFFFFF) == crc


def test_recognises_valid_request():
    assert d.is_discover_request(_make_request())


def test_rejects_garbage_and_wrong_type():
    assert not d.is_discover_request(b"hello world")
    assert not d.is_discover_request(d._packet(d.TYPE_DISCOVER_RPY, b""))


def test_rejects_corrupted_crc():
    pkt = bytearray(_make_request())
    pkt[-1] ^= 0xFF  # flip a CRC byte
    assert not d.is_discover_request(bytes(pkt))


def test_reply_is_well_formed():
    reply = d.build_discover_reply("A1B2C3D4", 4, "http://192.168.1.50:5004/")
    ptype, length = struct.unpack(">HH", reply[:4])
    assert ptype == d.TYPE_DISCOVER_RPY
    assert len(reply) == 4 + length + 4
    assert _crc_ok(reply)
    # base url and lineup url are advertised (trailing slash trimmed)
    assert b"http://192.168.1.50:5004" in reply
    assert b"http://192.168.1.50:5004/lineup.json" in reply


def test_device_id_coercion():
    assert d._device_id_int("A1B2C3D4") == 0xA1B2C3D4
    # non-hex ids fall back to a stable hash rather than crashing
    assert isinstance(d._device_id_int("not-hex!!"), int)
