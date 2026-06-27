# Copyright (C) 2026 Muneris Management Ltd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for XMLTV EPG handling."""

import gzip

from tunaar import epg

XMLTV = b"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="news.us"><display-name>News</display-name></channel>
  <channel id="sports.us"><display-name>Sports</display-name></channel>
  <channel id="movies.us"><display-name>Movies</display-name></channel>
  <programme start="20260622060000 +0000" channel="news.us"><title>Morning</title></programme>
  <programme start="20260622060000 +0000" channel="movies.us"><title>Film</title></programme>
</tv>
"""


def test_build_unfiltered():
    result = epg.build(XMLTV)
    assert result.channel_ids == {"news.us", "sports.us", "movies.us"}
    assert result.programme_count == 2


def test_build_filtered_to_lineup():
    result = epg.build(XMLTV, keep_ids={"news.us", "sports.us"})
    assert result.channel_ids == {"news.us", "sports.us"}
    # movies.us programme is dropped because it's not in the lineup.
    assert result.programme_count == 1
    assert b"movies.us" not in result.xml


def test_unique_titles_folds_subtitle():
    doc = (
        b'<tv><channel id="c1"><display-name>Sky</display-name></channel>'
        b'<programme start="1" channel="c1"><title>MLB Baseball</title>'
        b'<sub-title>Yankees vs Red Sox</sub-title></programme>'
        b'<programme start="2" channel="c1"><title>News</title></programme>'
        b'</tv>'
    )
    out = epg.build(doc, unique_titles=True).xml
    assert b"MLB Baseball \xe2\x80\x94 Yankees vs Red Sox" in out  # em dash
    # No sub-title and no desc → title unchanged.
    assert b"<title>News</title>" in out
    # Off by default.
    assert b"MLB Baseball</title>" in epg.build(doc).xml


def test_unique_titles_skips_episodic():
    # A programme with a season/episode tag must be left alone (Plex handles it).
    doc = (
        b'<tv><channel id="c1"><display-name>S</display-name></channel>'
        b'<programme start="1" channel="c1"><title>The Office</title>'
        b'<sub-title>Dinner Party</sub-title>'
        b'<episode-num system="xmltv_ns">3.13.</episode-num></programme></tv>'
    )
    import xml.etree.ElementTree as ET
    root = ET.fromstring(epg.build(doc, unique_titles=True).xml)
    assert root.find("programme/title").text == "The Office"  # unchanged


def test_unique_titles_desc_fallback():
    # No sub-title, but a desc → first sentence is folded in, truncated.
    doc = (
        b'<tv><channel id="c1"><display-name>S</display-name></channel>'
        b'<programme start="1" channel="c1"><title>Football</title>'
        b'<desc>Arsenal v Spurs. North London derby from the Emirates.</desc></programme>'
        b'</tv>'
    )
    import xml.etree.ElementTree as ET
    root = ET.fromstring(epg.build(doc, unique_titles=True).xml)
    title = root.find("programme/title").text
    assert title.startswith("Football — Arsenal v Spurs")  # first sentence only
    assert "North London derby" not in title


def test_norm_name():
    assert epg.norm_name("BBC One HD") == epg.norm_name("BBC ONE")
    assert epg.norm_name("Channel 4 (1080p)") == "channel4"


def test_name_to_id_index():
    doc = b'<tv><channel id="bbc1.uk"><display-name>BBC One</display-name></channel></tv>'
    result = epg.build(doc)
    assert result.name_to_id.get("bbcone") == "bbc1.uk"


def test_build_many_merges_and_dedupes():
    doc_a = b'<tv><channel id="a"/><programme channel="a"><title>X</title></programme></tv>'
    doc_b = b'<tv><channel id="a"/><channel id="b"/><programme channel="b"><title>Y</title></programme></tv>'
    result = epg.build_many([doc_a, doc_b])
    # channel "a" appears in both but is de-duplicated
    assert result.channel_ids == {"a", "b"}
    assert result.programme_count == 2


def test_build_many_skips_unparseable_doc():
    good = b'<tv><channel id="a"/></tv>'
    result = epg.build_many([b"not xml", good])
    assert result.channel_ids == {"a"}


def test_fetch_handles_gzip(monkeypatch):
    payload = gzip.compress(XMLTV)

    class FakeResp:
        content = payload
        def raise_for_status(self):  # noqa: D401
            pass

    monkeypatch.setattr(epg.requests, "get", lambda *a, **k: FakeResp())
    raw = epg.fetch("http://example.com/epg.xml.gz")
    assert raw.startswith(b"<?xml")
    assert b"news.us" in raw
