# Copyright (C) 2026 Martin Carpenter
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for tuner-slot accounting and the ffmpeg command builder."""

import pytest

from tunaar import proxy


def test_tuner_capacity_enforced():
    mgr = proxy.TunerManager(capacity=2)
    a = mgr.acquire("1", "A")
    b = mgr.acquire("2", "B")
    assert mgr.in_use == 2
    with pytest.raises(proxy.TunersBusy):
        mgr.acquire("3", "C")
    mgr.release(a)
    # A slot freed up — acquiring works again.
    c = mgr.acquire("3", "C")
    assert mgr.in_use == 2
    mgr.release(b)
    mgr.release(c)
    assert mgr.in_use == 0


def test_active_reports_sessions():
    mgr = proxy.TunerManager(capacity=4)
    mgr.acquire("5", "Sports")
    active = mgr.active()
    assert len(active) == 1
    assert active[0]["channel"] == "5"
    assert active[0]["name"] == "Sports"
    assert "uptime" in active[0]


def test_double_release_is_safe():
    mgr = proxy.TunerManager(capacity=1)
    s = mgr.acquire("1", "A")
    mgr.release(s)
    mgr.release(s)  # must not error or go negative
    assert mgr.in_use == 0


def test_ffmpeg_cmd_has_reconnect_and_mpegts():
    cmd = proxy.build_ffmpeg_cmd(
        "http://src/stream", ffmpeg_path="ffmpeg", user_agent="UA"
    )
    assert cmd[0] == "ffmpeg"
    assert "-reconnect" in cmd
    assert "http://src/stream" in cmd
    assert cmd[-1] == "pipe:1"
    # remux, don't transcode
    assert "copy" in cmd
    assert "mpegts" in cmd
