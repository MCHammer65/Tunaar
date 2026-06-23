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
