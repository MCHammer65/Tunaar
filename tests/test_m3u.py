"""Tests for the M3U playlist parser."""

from tunaar import m3u

SAMPLE = """#EXTM3U
#EXTINF:-1 tvg-id="news.us" tvg-name="News" tvg-logo="http://logo/news.png" group-title="News",News Channel
http://example.com/news.m3u8
#EXTINF:-1 tvg-chno="7" tvg-id="sports.us" group-title="Sports",Sports HD
http://example.com/sports.m3u8
#EXTINF:-1,Bare Channel
http://example.com/bare.m3u8
"""


def test_parses_all_channels():
    assert len(m3u.parse(SAMPLE)) == 3


def test_extracts_attributes():
    news = m3u.parse(SAMPLE)[0]
    assert news.name == "News Channel"
    assert news.tvg_id == "news.us"
    assert news.logo == "http://logo/news.png"
    assert news.group == "News"
    assert news.url == "http://example.com/news.m3u8"


def test_uses_tvg_chno_for_number():
    assert m3u.parse(SAMPLE)[1].number == "7"


def test_auto_numbers_avoid_collisions():
    numbers = [c.number for c in m3u.parse(SAMPLE)]
    assert numbers == ["1", "7", "2"]
    assert len(set(numbers)) == len(numbers)


def test_bare_extinf_without_attrs():
    bare = m3u.parse(SAMPLE)[2]
    assert bare.name == "Bare Channel"
    assert bare.url == "http://example.com/bare.m3u8"


def test_ignores_url_without_extinf():
    assert m3u.parse("#EXTM3U\nhttp://example.com/orphan.m3u8\n") == []


def test_discovers_epg_url_from_header():
    text = '#EXTM3U url-tvg="http://epg.example/guide.xml.gz"\n#EXTINF:-1,A\nhttp://a/1\n'
    doc = m3u.parse_document(text)
    assert doc.epg_urls == ["http://epg.example/guide.xml.gz"]


def test_ungrouped_channel_gets_undefined():
    assert m3u.parse(SAMPLE)[2].group == m3u.UNGROUPED


def test_load_sources_merges_and_overrides_group(monkeypatch):
    a = '#EXTM3U url-tvg="http://epg/a.xml"\n#EXTINF:-1,A\nhttp://a/1\n'
    b = '#EXTINF:-1 group-title="Sports",B\nhttp://b/1\n'
    monkeypatch.setattr(
        m3u, "_fetch_text", lambda src, **k: a if "a.m3u" in src else b
    )
    playlist = m3u.load_sources(
        [{"url": "http://x/a.m3u"}, {"url": "http://x/b.m3u", "group": "Custom"}]
    )
    assert [c.name for c in playlist.channels] == ["A", "B"]
    assert playlist.channels[1].group == "Custom"  # override applied
    nums = [c.number for c in playlist.channels]
    assert len(set(nums)) == 2  # merged numbering, no collisions
    assert playlist.epg_urls == ["http://epg/a.xml"]  # discovered from header
