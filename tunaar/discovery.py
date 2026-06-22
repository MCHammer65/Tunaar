"""HDHomeRun network-discovery responder.

Plex (and other HDHomeRun clients) find network tuners by broadcasting a small
binary "discover request" UDP packet to port 65001. Real HDHomeRun devices
reply with their device id, tuner count and base URL; the client then fetches
``<base>/discover.json``. Implementing this responder is what makes Tunaar
appear automatically in Plex's DVR setup instead of needing a manual IP entry.

The wire format follows Silicondust's libhdhomerun: a 4-byte header
(``type`` u16 + payload ``length`` u16, big-endian), a TLV payload, and a
trailing little-endian CRC32 over header+payload.
"""

from __future__ import annotations

import binascii
import socket
import struct
import threading

DISCOVERY_PORT = 65001

TYPE_DISCOVER_REQ = 0x0002
TYPE_DISCOVER_RPY = 0x0003

TAG_DEVICE_TYPE = 0x01
TAG_DEVICE_ID = 0x02
TAG_TUNER_COUNT = 0x10
TAG_BASE_URL = 0x2A
TAG_DEVICE_AUTH_STR = 0x2B
TAG_LINEUP_URL = 0x27

DEVICE_TYPE_TUNER = 0x00000001


def _tlv(tag: int, value: bytes) -> bytes:
    length = len(value)
    if length <= 127:
        len_bytes = bytes([length])
    else:  # HDHomeRun variable-length encoding
        len_bytes = bytes([(length & 0x7F) | 0x80, (length >> 7) & 0xFF])
    return bytes([tag]) + len_bytes + value


def _packet(ptype: int, payload: bytes) -> bytes:
    body = struct.pack(">HH", ptype, len(payload)) + payload
    crc = binascii.crc32(body) & 0xFFFFFFFF
    return body + struct.pack("<I", crc)


def _device_id_int(device_id: str) -> int:
    try:
        return int(device_id, 16) & 0xFFFFFFFF
    except ValueError:
        return binascii.crc32(device_id.encode()) & 0xFFFFFFFF


def build_discover_reply(
    device_id: str, tuner_count: int, base_url: str
) -> bytes:
    """Build a discover-reply packet advertising this tuner."""
    base_url = base_url.rstrip("/")
    payload = b"".join(
        [
            _tlv(TAG_DEVICE_TYPE, struct.pack(">I", DEVICE_TYPE_TUNER)),
            _tlv(TAG_DEVICE_ID, struct.pack(">I", _device_id_int(device_id))),
            _tlv(TAG_TUNER_COUNT, bytes([tuner_count & 0xFF])),
            _tlv(TAG_BASE_URL, base_url.encode()),
            _tlv(TAG_LINEUP_URL, f"{base_url}/lineup.json".encode()),
            _tlv(TAG_DEVICE_AUTH_STR, b"tunaar"),
        ]
    )
    return _packet(TYPE_DISCOVER_RPY, payload)


def is_discover_request(data: bytes) -> bool:
    """True if ``data`` looks like a valid HDHomeRun discover request."""
    if len(data) < 8:
        return False
    ptype, length = struct.unpack(">HH", data[:4])
    if ptype != TYPE_DISCOVER_REQ:
        return False
    if len(data) < 4 + length + 4:
        return False
    body = data[: 4 + length]
    crc = struct.unpack("<I", data[4 + length : 4 + length + 4])[0]
    return (binascii.crc32(body) & 0xFFFFFFFF) == crc


def local_ip_for(client_ip: str) -> str:
    """Best-effort local interface IP that routes to ``client_ip``."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((client_ip, 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class DiscoveryServer:
    """Listens for discover requests and replies with this tuner's details."""

    def __init__(self, config, sock: socket.socket) -> None:
        self._config = config
        self._sock = sock
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="tunaar-discovery", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def _base_url(self, client_ip: str) -> str:
        if self._config.advertised_url:
            return self._config.advertised_url
        return f"http://{local_ip_for(client_ip)}:{self._config.port}"

    def _run(self) -> None:
        self._sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if is_discover_request(data):
                reply = build_discover_reply(
                    self._config.device_id,
                    self._config.tuner_count,
                    self._base_url(addr[0]),
                )
                try:
                    self._sock.sendto(reply, addr)
                except OSError:
                    pass


def start(config, port: int = DISCOVERY_PORT) -> DiscoveryServer:
    """Bind the discovery socket and start the responder thread.

    Raises ``OSError`` if the port can't be bound (e.g. already in use); the
    caller can log and continue without discovery.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    sock.bind(("", port))
    server = DiscoveryServer(config, sock)
    server.start()
    return server
