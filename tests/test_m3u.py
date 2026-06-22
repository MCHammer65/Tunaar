"""Tests for the M3U playlist parser."""

from plexiptv import m3u

SAMPLE = """#EXTM3U
#EXTINF:-1 tvg-id="news.us" tvg-name="News" tvg-logo="http://logo/news.png" group-title="News",News Channel
http://example.com/news.m3u8
#EXTINF:-1 tvg-chno="7" tvg-id="sports.us" group-title="Sports",Sports HD
http://example.com/sports.m3u8
#EXTINF:-1,Bare Channel
http://example.com/bare.m3u8
"""


def test_parses_all_channels():
    channels = m3u.parse(SAMPLE)
    assert len(channels) == 3


def test_extracts_attributes():
    news = m3u.parse(SAMPLE)[0]
    assert news.name == "News Channel"
    assert news.tvg_id == "news.us"
    assert news.logo == "http://logo/news.png"
    assert news.group == "News"
    assert news.url == "http://example.com/news.m3u8"


def test_uses_tvg_chno_for_number():
    sports = m3u.parse(SAMPLE)[1]
    assert sports.number == "7"


def test_auto_numbers_avoid_collisions():
    channels = m3u.parse(SAMPLE)
    numbers = [c.number for c in channels]
    # tvg-chno "7" is reserved, so auto-numbering must skip it.
    assert numbers == ["1", "7", "2"]
    assert len(set(numbers)) == len(numbers)


def test_bare_extinf_without_attrs():
    bare = m3u.parse(SAMPLE)[2]
    assert bare.name == "Bare Channel"
    assert bare.url == "http://example.com/bare.m3u8"


def test_ignores_url_without_extinf():
    text = "#EXTM3U\nhttp://example.com/orphan.m3u8\n"
    assert m3u.parse(text) == []
