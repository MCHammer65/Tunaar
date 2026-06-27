# Copyright (C) 2026 Muneris Management Ltd
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


def test_stabilize_gives_up_on_dead_source(monkeypatch):
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def make_source():
        calls["n"] += 1
        return iter(())  # dies immediately, no bytes

    out = list(proxy.stabilize(make_source, max_retries=2))
    assert out == []
    # failures 1, 2, then 3 > max_retries → stop. Three attempts.
    assert calls["n"] == 3


def test_stabilize_restarts_after_data_then_gives_up(monkeypatch):
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    scripts = [[b"a", b"b"], [], []]
    calls = {"n": 0}

    def make_source():
        i = calls["n"]
        calls["n"] += 1
        return iter(scripts[i] if i < len(scripts) else ())

    # An instant run (even with data) counts as a failure, so the budget winds
    # down: produce a,b then two empties → stop after the third attempt.
    out = list(proxy.stabilize(make_source, max_retries=2))
    assert out == [b"a", b"b"]
    assert calls["n"] == 3


def test_stabilize_resets_budget_after_healthy_run(monkeypatch):
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    # A clock that advances 100s per call, so every run clears the settle window.
    ticks = iter(range(0, 100000, 100))
    monkeypatch.setattr(proxy.time, "time", lambda: next(ticks))
    scripts = [[b"x"], [b"x"], [b"x"], [], []]
    calls = {"n": 0}

    def make_source():
        i = calls["n"]
        calls["n"] += 1
        return iter(scripts[i] if i < len(scripts) else ())

    out = list(proxy.stabilize(make_source, max_retries=1, settle=10))
    # 3 healthy runs keep resetting the budget; only the trailing empties trip
    # it (failures 1, then 2 > 1). Without reset it'd give up far sooner.
    assert out == [b"x", b"x", b"x"]
    assert calls["n"] == 5


def test_stabilize_no_restart_on_client_disconnect(monkeypatch):
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    closed = {"v": False}

    def infinite():
        try:
            while True:
                yield b"x"
        finally:
            closed["v"] = True

    def make_source():
        calls["n"] += 1
        return infinite()

    gen = proxy.stabilize(make_source)
    assert next(gen) == b"x"
    gen.close()  # client disconnected
    assert calls["n"] == 1  # not restarted
    assert closed["v"] is True  # underlying source was torn down


def test_supervised_fails_over_to_next_source(monkeypatch):
    import itertools
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    calls = []

    def dead():
        calls.append("a")
        return iter(())  # primary is dead

    def live():
        calls.append("b")
        return iter((b"x", b"y"))  # alternate produces

    # Primary dies → fails over to the live alternate; take its first output.
    out = list(itertools.islice(proxy.supervised([dead, live], max_retries=5), 2))
    assert out == [b"x", b"y"]
    assert calls[0] == "a" and "b" in calls  # tried primary, then alternate


def test_supervised_single_source_equals_stabilize(monkeypatch):
    monkeypatch.setattr(proxy.time, "sleep", lambda *_: None)
    n = {"c": 0}

    def make():
        n["c"] += 1
        return iter(())

    assert list(proxy.supervised([make], max_retries=2)) == []
    assert n["c"] == 3  # failures 1,2,3 > 2 → stop


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
