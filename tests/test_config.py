"""Tests for configuration loading, validation and atomic saving."""

import json
import os

import pytest

from tunaar.config import Config


def test_defaults_when_no_file(tmp_path):
    cfg = Config.load(str(tmp_path / "missing.json"))
    assert cfg.friendly_name == "Tunaar"
    assert cfg.tuner_count == 4
    assert cfg.stream_mode == "ffmpeg"


def test_generates_and_persists_device_id(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"playlist": "x.m3u"}))
    cfg = Config.load(str(path))
    assert cfg.device_id  # generated
    # Persisted back to disk so the tuner identity is stable.
    on_disk = json.loads(path.read_text())
    assert on_disk["device_id"] == cfg.device_id


def test_rejects_bad_stream_mode(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stream_mode": "bogus"}))
    with pytest.raises(ValueError):
        Config.load(str(path))


def test_atomic_save_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(str(path))
    cfg.tuner_count = 9
    cfg.save()
    reloaded = Config.load(str(path))
    assert reloaded.tuner_count == 9
    # No leftover temp files from the atomic write.
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_env_overrides_with_coercion(tmp_path):
    env = {
        "TUNAAR_PLAYLIST": "http://example.com/list.m3u",
        "TUNAAR_TUNER_COUNT": "6",
        "TUNAAR_FILTER_EPG_TO_LINEUP": "false",
        "TUNAAR_FRIENDLY_NAME": "Living Room",
    }
    cfg = Config.load(str(tmp_path / "config.json"), env=env)
    assert cfg.playlist == "http://example.com/list.m3u"
    assert cfg.tuner_count == 6  # coerced to int
    assert cfg.filter_epg_to_lineup is False  # coerced to bool
    assert cfg.friendly_name == "Living Room"


def test_env_overrides_take_precedence_over_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"playlist": "from-file.m3u"}))
    cfg = Config.load(str(path), env={"TUNAAR_PLAYLIST": "from-env.m3u"})
    assert cfg.playlist == "from-env.m3u"


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"playlist": "x.m3u", "totally_unknown": 1}))
    cfg = Config.load(str(path))  # must not raise
    assert not hasattr(cfg, "totally_unknown")
