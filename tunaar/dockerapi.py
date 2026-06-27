# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal Docker Engine API client over the unix socket.

Just enough to let Tunaar pull a new image and recreate its own container for
the console's one-click update. Talks raw HTTP to ``/var/run/docker.sock`` so we
don't pull in the full docker SDK. All calls are best-effort and raise
``DockerError`` on failure so the caller can fall back gracefully.
"""

from __future__ import annotations

import http.client
import json
import os
import socket

DEFAULT_SOCK = "/var/run/docker.sock"


class DockerError(Exception):
    pass


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 120) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


class DockerClient:
    def __init__(self, sock_path: str = DEFAULT_SOCK) -> None:
        self.sock_path = sock_path

    @staticmethod
    def available(sock_path: str = DEFAULT_SOCK) -> bool:
        return os.path.exists(sock_path)

    def _request(self, method: str, path: str, body=None, read_stream=False):
        conn = _UnixHTTPConnection(self.sock_path)
        try:
            data = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if data else {}
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status >= 400:
                raise DockerError(f"{method} {path} -> {resp.status}: {raw[:200]!r}")
            return resp.status, raw
        except OSError as exc:
            raise DockerError(str(exc)) from exc
        finally:
            conn.close()

    def get_json(self, path: str):
        _, raw = self._request("GET", path)
        return json.loads(raw or b"null")

    def self_id(self) -> str:
        return os.environ.get("HOSTNAME") or socket.gethostname()

    def inspect_container(self, cid: str) -> dict:
        return self.get_json(f"/containers/{cid}/json")

    def inspect_image(self, ref: str) -> dict:
        return self.get_json(f"/images/{ref}/json")

    def pull(self, repo: str, tag: str = "latest") -> None:
        # POST returns a stream of progress JSON; we just drain it.
        self._request("POST", f"/images/create?fromImage={repo}&tag={tag}")

    def create_container(self, name: str, spec: dict) -> str:
        _, raw = self._request("POST", f"/containers/create?name={name}", body=spec)
        return json.loads(raw)["Id"]

    def start(self, cid: str) -> None:
        self._request("POST", f"/containers/{cid}/start")

    def stop(self, cid: str, timeout: int = 10) -> None:
        self._request("POST", f"/containers/{cid}/stop?t={timeout}")

    def remove(self, cid: str, force: bool = True) -> None:
        self._request("DELETE", f"/containers/{cid}?force={'true' if force else 'false'}")

    def rename(self, cid: str, name: str) -> None:
        self._request("POST", f"/containers/{cid}/rename?name={name}")
