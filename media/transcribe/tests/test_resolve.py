import json
from urllib.parse import parse_qs, urlparse

import pytest

from transcribe import resolve

SPOTIFY = "https://open.spotify.com/show/3Kfpi2wm8bjRVL5YEV6asV"
TITLE = "Certified - AWS Certified Cloud Practitioner Audio Course"
FEED = "https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner"


def spotify_page(title, author="Jason Edwards"):
    return (
        '<html><head><meta property="og:site_name" content="Spotify"/>'
        f'<meta property="og:title" content="{title}"/>'
        f'<meta property="og:description" content="Podcast · {author} · Long text"/>'
        "</head></html>").encode()


def itunes(results):
    return json.dumps({"resultCount": len(results), "results": results}).encode()


def fake_http(pages):
    calls = []

    def get(url):
        calls.append(url)
        for prefix, body in pages.items():
            if url.startswith(prefix):
                return body
        raise AssertionError(f"unexpected URL {url}")
    get.calls = calls
    return get


def test_classify():
    assert resolve.classify(SPOTIFY) == ("spotify", "3Kfpi2wm8bjRVL5YEV6asV")
    assert resolve.classify("https://podcasts.apple.com/us/podcast/x/id1836789493?i=1") == (
        "apple", "1836789493")
    assert resolve.classify(FEED) == ("feed", FEED)
    with pytest.raises(resolve.ResolveError):
        resolve.classify("https://open.spotify.com/episode/abc")
    with pytest.raises(resolve.ResolveError):
        resolve.classify("ftp://example.org/feed")


def test_spotify_exact_match():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page(TITLE),
        "https://itunes.apple.com/search": itunes([
            {"collectionName": "Something Else", "artistName": "X", "feedUrl": "https://other/feed"},
            {"collectionName": TITLE, "artistName": "Jason Edwards", "feedUrl": FEED},
        ]),
    })
    found = resolve.resolve_url(SPOTIFY, http)
    assert found.feed_url == FEED
    assert found.title == TITLE
    query = parse_qs(urlparse(http.calls[1]).query)
    assert query["term"] == [TITLE] and query["media"] == ["podcast"]


def test_spotify_html_entities_are_decoded():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page("Tom &amp; Jerry&#39;s Show", "A"),
        "https://itunes.apple.com/search": itunes([
            {"collectionName": "Tom & Jerry's Show", "artistName": "A", "feedUrl": FEED}]),
    })
    assert resolve.resolve_url(SPOTIFY, http).feed_url == FEED


def test_spotify_no_exact_match_refuses_and_never_picks_another_show():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page("☁️AWS Cloud Practitioner Essentials", "Thomas Sxt"),
        "https://itunes.apple.com/search": itunes([
            {"collectionName": "AWS Cloud Practitioner Essentials", "artistName": "Someone",
             "feedUrl": "https://similar/feed"},
        ]),
    })
    with pytest.raises(resolve.ResolveError, match="kein öffentlicher Feed gefunden"):
        resolve.resolve_url(SPOTIFY, http)


def test_same_title_other_author_is_refused():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page(TITLE, "Jason Edwards"),
        "https://itunes.apple.com/search": itunes([
            {"collectionName": TITLE, "artistName": "Copycat Media", "feedUrl": "https://copy/feed"}]),
    })
    with pytest.raises(resolve.ResolveError, match="kein öffentlicher Feed gefunden"):
        resolve.resolve_url(SPOTIFY, http)


def test_exact_title_without_feed_url_is_refused():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page(TITLE),
        "https://itunes.apple.com/search": itunes([{"collectionName": TITLE, "artistName": "Jason Edwards"}]),
    })
    with pytest.raises(resolve.ResolveError, match="kein öffentlicher Feed gefunden"):
        resolve.resolve_url(SPOTIFY, http)


def test_two_different_feeds_with_the_exact_title_are_refused():
    http = fake_http({
        "https://open.spotify.com/show/": spotify_page(TITLE, ""),
        "https://itunes.apple.com/search": itunes([
            {"collectionName": TITLE, "artistName": "A", "feedUrl": "https://a/feed"},
            {"collectionName": TITLE, "artistName": "B", "feedUrl": "https://b/feed"}]),
    })
    with pytest.raises(resolve.ResolveError, match="mehrdeutig"):
        resolve.resolve_url(SPOTIFY, http)


def test_spotify_page_without_title_is_refused():
    http = fake_http({"https://open.spotify.com/show/": b"<html></html>"})
    with pytest.raises(resolve.ResolveError, match="og:title"):
        resolve.resolve_url(SPOTIFY, http)


def test_apple_lookup():
    http = fake_http({"https://itunes.apple.com/lookup?id=1836789493": itunes(
        [{"collectionName": TITLE, "artistName": "Jason Edwards", "feedUrl": FEED}])})
    found = resolve.resolve_url("https://podcasts.apple.com/us/podcast/certified/id1836789493", http)
    assert found.feed_url == FEED


def test_apple_lookup_without_feed_is_refused():
    http = fake_http({"https://itunes.apple.com/lookup": itunes([])})
    with pytest.raises(resolve.ResolveError, match="kein öffentlicher Feed gefunden"):
        resolve.resolve_url("https://podcasts.apple.com/us/podcast/x/id1", http)


def test_feed_url_passes_through_without_network():
    http = fake_http({})
    assert resolve.resolve_url(FEED, http).feed_url == FEED
    assert http.calls == []


def test_never_downloads_from_spotify_media_hosts():
    with pytest.raises(resolve.ResolveError):
        resolve.classify("https://open.spotify.com/episode/123")


def test_counter_proof_guard_is_load_bearing(monkeypatch):
    """Disable the exact-title guard: the 'never another show' test must then fail."""
    monkeypatch.setattr(resolve, "is_same_show", lambda *a, **k: True)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_spotify_no_exact_match_refuses_and_never_picks_another_show()
