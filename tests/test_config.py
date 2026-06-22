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


def test_normalize_folds_playlist_into_sources(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"playlist": "http://a/1.m3u, http://b/2.m3u"}))
    cfg = Config.load(str(path))
    assert [s["url"] for s in cfg.sources] == ["http://a/1.m3u", "http://b/2.m3u"]


def test_effective_epg_urls_merges_auto(tmp_path):
    cfg = Config.load(str(tmp_path / "c.json"), env={"TUNAAR_EPG_URL": "http://manual/x.xml"})
    urls = cfg.effective_epg_urls(["http://discovered/y.xml", "http://manual/x.xml"])
    # manual first, discovered appended, de-duplicated
    assert urls == ["http://manual/x.xml", "http://discovered/y.xml"]


def test_effective_epg_urls_ignores_auto_when_disabled(tmp_path):
    cfg = Config.load(str(tmp_path / "c.json"), env={"TUNAAR_EPG_AUTO": "false"})
    assert cfg.effective_epg_urls(["http://discovered/y.xml"]) == []


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"playlist": "x.m3u", "totally_unknown": 1}))
    cfg = Config.load(str(path))  # must not raise
    assert not hasattr(cfg, "totally_unknown")
