# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for self-update helpers (Docker calls mocked — no daemon needed)."""

from tunaar import selfupdate as su
from tunaar.dockerapi import DockerClient


def test_split_ref_variants():
    assert su._split_ref("ghcr.io/mchammer65/plexiptv:latest") == (
        "ghcr.io/mchammer65/plexiptv", "latest")
    assert su._split_ref("ghcr.io/mchammer65/plexiptv") == (
        "ghcr.io/mchammer65/plexiptv", "latest")
    # digest refs fall back to the default image
    repo, tag = su._split_ref("ghcr.io/x/y@sha256:abc")
    assert tag == "latest"


def test_image_ref_prefers_config_then_default(monkeypatch):
    monkeypatch.delenv("TUNAAR_UPDATE_IMAGE", raising=False)
    assert su._image_ref({"Config": {"Image": "ghcr.io/a/b:1"}}) == "ghcr.io/a/b:1"
    # digest-only config image falls back to the default tag
    assert su._image_ref({"Config": {"Image": "x@sha256:deadbeef"}}) == su.DEFAULT_IMAGE
    monkeypatch.setenv("TUNAAR_UPDATE_IMAGE", "custom/img:tag")
    assert su._image_ref({"Config": {"Image": "ignored"}}) == "custom/img:tag"


def test_build_spec_carries_runtime_config():
    me = {
        "Config": {"Image": "old", "Env": ["TUNAAR_PLAYLIST=x"], "Labels": {"a": "b"}},
        "HostConfig": {"Binds": ["/cfg:/config"], "NetworkMode": "host",
                       "RestartPolicy": {"Name": "unless-stopped"}},
    }
    spec = su._build_spec(me, "ghcr.io/mchammer65/plexiptv:latest")
    assert spec["Image"] == "ghcr.io/mchammer65/plexiptv:latest"
    assert spec["Env"] == ["TUNAAR_PLAYLIST=x"]
    assert spec["HostConfig"]["NetworkMode"] == "host"
    assert spec["HostConfig"]["Binds"] == ["/cfg:/config"]


def test_check_without_socket(monkeypatch):
    monkeypatch.setattr(DockerClient, "available", staticmethod(lambda *a: False))
    assert su.check()["socket"] is False


def test_apply_detects_already_latest(monkeypatch):
    monkeypatch.setattr(DockerClient, "available", staticmethod(lambda *a: True))

    class FakeClient:
        def self_id(self): return "self"
        def inspect_container(self, cid):
            return {"Id": "abc", "Name": "/tunaar", "Image": "sha256:same",
                    "Config": {"Image": "ghcr.io/mchammer65/plexiptv:latest"},
                    "HostConfig": {}}
        def pull(self, repo, tag): pass
        def inspect_image(self, ref): return {"Id": "sha256:same"}

    result = su.apply(client=FakeClient())
    assert result["updated"] is False


def test_apply_launches_helper_when_newer(monkeypatch):
    monkeypatch.setattr(DockerClient, "available", staticmethod(lambda *a: True))
    actions = {}

    class FakeClient:
        def self_id(self): return "self"
        def inspect_container(self, cid):
            return {"Id": "abc", "Name": "/tunaar", "Image": "sha256:old",
                    "Config": {"Image": "ghcr.io/mchammer65/plexiptv:latest",
                               "Env": ["X=1"]},
                    "HostConfig": {"NetworkMode": "host"}}
        def pull(self, repo, tag): actions["pulled"] = (repo, tag)
        def inspect_image(self, ref): return {"Id": "sha256:new"}
        def remove(self, name): pass
        def create_container(self, name, spec):
            actions["created"] = (name, spec); return "helper-id"
        def start(self, cid): actions["started"] = cid

    result = su.apply(client=FakeClient())
    assert result["updated"] is True
    assert actions["pulled"] == ("ghcr.io/mchammer65/plexiptv", "latest")
    assert actions["created"][0] == su.HELPER_NAME
    # helper gets the recreate spec + old container id via env
    env = actions["created"][1]["Env"]
    assert any(e.startswith("TUNAAR_OLD_ID=abc") for e in env)
    assert actions["started"] == "helper-id"
