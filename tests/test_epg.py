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


def test_unique_titles_injects_date_episode_num():
    # No sub-title and no real episode-num → inject a synthetic date-based
    # episode-num (Julian day) so Plex distinguishes airings without
    # cluttering the title. 27 June 2026 is day 178 of a non-leap year.
    doc = (
        b'<tv><channel id="c1"><display-name>S</display-name></channel>'
        b'<programme start="20260627060000 +0000" channel="c1"><title>News</title></programme>'
        b'<programme start="20260627223000 +0000" channel="c1"><title>News</title></programme>'
        b'</tv>'
    )
    import xml.etree.ElementTree as ET
    root = ET.fromstring(epg.build(doc, unique_titles=True).xml)
    progs = root.findall("programme")
    # Titles stay clean — no folded description.
    assert all(p.find("title").text == "News" for p in progs)

    def nums(p, system):
        return [
            e.text for e in p.findall("episode-num") if e.get("system") == system
        ]

    # First airing: S2026E178, second same-day airing gets an incrementing part.
    assert nums(progs[0], "onscreen") == ["S2026E178"]
    assert nums(progs[1], "onscreen") == ["S2026E178.2"]
    # xmltv_ns is 0-indexed: 2025.177.<part>.
    assert nums(progs[0], "xmltv_ns") == ["2025.177.0"]
    assert nums(progs[1], "xmltv_ns") == ["2025.177.1"]


def test_unique_titles_no_episode_num_without_date():
    # Without a parseable start date there's nothing to inject — leave it be.
    doc = (
        b'<tv><channel id="c1"><display-name>S</display-name></channel>'
        b'<programme start="1" channel="c1"><title>News</title></programme></tv>'
    )
    import xml.etree.ElementTree as ET
    root = ET.fromstring(epg.build(doc, unique_titles=True).xml)
    prog = root.find("programme")
    assert prog.find("title").text == "News"
    assert prog.find("episode-num") is None


def test_align_rekeys_channels_to_numbers():
    import xml.etree.ElementTree as ET
    doc = (
        b'<tv><channel id="bbc1.uk"><display-name>BBC One</display-name></channel>'
        b'<programme start="20260627060000" channel="bbc1.uk"><title>Breakfast</title></programme>'
        b'</tv>'
    )
    result = epg.align(doc, {"3": "bbc1.uk"})
    root = ET.fromstring(result.xml)
    ch = root.find("channel")
    # Channel id is now the lineup number; the number is also a display-name.
    assert ch.get("id") == "3"
    names = [d.text for d in ch.findall("display-name")]
    assert "BBC One" in names and "3" in names
    # The programme is re-pointed at the number.
    assert root.find("programme").get("channel") == "3"
    assert result.channel_ids == {"3"}
    assert result.programme_count == 1


def test_align_duplicates_shared_guide_channel():
    # Two lineup channels pointing at the same guide id each get their own copy.
    import xml.etree.ElementTree as ET
    doc = (
        b'<tv><channel id="news.x"><display-name>News</display-name></channel>'
        b'<programme start="20260627060000" channel="news.x"><title>Headlines</title></programme>'
        b'</tv>'
    )
    result = epg.align(doc, {"5": "news.x", "6": "news.x"})
    root = ET.fromstring(result.xml)
    ids = sorted(c.get("id") for c in root.findall("channel"))
    assert ids == ["5", "6"]
    chans = sorted(p.get("channel") for p in root.findall("programme"))
    assert chans == ["5", "6"]


def test_align_skips_unmatched_and_applies_unique_titles():
    import xml.etree.ElementTree as ET
    doc = (
        b'<tv><channel id="c1"><display-name>Movies</display-name></channel>'
        b'<programme start="20260627060000" channel="c1"><title>Film</title></programme>'
        b'</tv>'
    )
    # "9" matches a real channel; "10" points at a missing id (still emitted,
    # just with no programmes) — align never raises on a stale mapping.
    result = epg.align(doc, {"9": "c1"}, unique_titles=True)
    root = ET.fromstring(result.xml)
    prog = root.find("programme")
    nums = [e.text for e in prog.findall("episode-num") if e.get("system") == "onscreen"]
    assert nums == ["S2026E178"]  # date-based episode-num injected post-align


def test_build_embeds_logos_and_stamps_tz():
    import xml.etree.ElementTree as ET
    doc = (
        b'<tv><channel id="c1"><display-name>One</display-name></channel>'
        b'<programme start="20260627060000" stop="20260627070000 +0000" channel="c1">'
        b'<title>Show</title></programme></tv>'
    )
    out = epg.build(doc, logos={"c1": "http://logo/c1.png"}, tz_offset="+0100").xml
    root = ET.fromstring(out)
    # Logo injected as <icon>.
    assert root.find("channel/icon").get("src") == "http://logo/c1.png"
    prog = root.find("programme")
    # Bare start gets the offset; the already-offset stop is left untouched.
    assert prog.get("start") == "20260627060000 +0100"
    assert prog.get("stop") == "20260627070000 +0000"


def test_align_embeds_logos_by_number():
    import xml.etree.ElementTree as ET
    doc = b'<tv><channel id="keep"><display-name>K</display-name></channel></tv>'
    out = epg.align(doc, {"5": "keep"}, logos={"5": "http://logo/5.png"}).xml
    root = ET.fromstring(out)
    assert root.find("channel/icon").get("src") == "http://logo/5.png"


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
