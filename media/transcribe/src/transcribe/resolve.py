"""Turn a Spotify show URL, an Apple Podcasts URL or a feed URL into a public RSS feed.

Spotify is only read for the show's title (og:title) and author; audio never
comes from Spotify. The feed comes from Apple's public podcast directory and
must match the title exactly - a similar show is never accepted.
"""

import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

NO_FEED = ("kein öffentlicher Feed gefunden – Spotify-exklusiv oder nicht verzeichnet; "
           "nichts wird transkribiert")


class ResolveError(Exception):
    pass


@dataclass
class Found:
    feed_url: str
    title: str | None = None
    author: str | None = None
    via: str = "feed"


def classify(url):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ResolveError(f"keine http(s)-URL: {url!r}")
    host = parsed.netloc.lower()
    if host == "spotify.com" or host.endswith(".spotify.com"):
        m = re.fullmatch(r"/(?:intl-[a-z-]+/)?show/([A-Za-z0-9]+)/?", parsed.path)
        if not m:
            raise ResolveError("nur Spotify-Show-URLs (open.spotify.com/show/<id>) werden aufgelöst; "
                               "von Spotify selbst wird nie etwas heruntergeladen")
        return "spotify", m.group(1)
    if host in ("podcasts.apple.com", "itunes.apple.com"):
        m = re.search(r"/id(\d+)", parsed.path)
        if not m:
            raise ResolveError(f"keine Podcast-ID (/id<zahl>) in der Apple-URL: {url}")
        return "apple", m.group(1)
    return "feed", url.strip()


def spotify_url(show_id):
    return f"https://open.spotify.com/show/{show_id}"


def search_url(title):
    return "https://itunes.apple.com/search?" + urlencode({"term": title, "media": "podcast"})


def lookup_url(apple_id):
    return f"https://itunes.apple.com/lookup?id={apple_id}"


def _meta(page, prop):
    for tag in re.findall(r"<meta\b[^>]*>", page):
        if re.search(rf'property="{re.escape(prop)}"', tag):
            m = re.search(r'content="([^"]*)"', tag)
            if m:
                return html.unescape(m.group(1)).strip()
    return None


def spotify_show(page_bytes):
    """(title, author) from a Spotify show page; author may be None."""
    page = page_bytes.decode("utf-8", "replace")
    title = _meta(page, "og:title")
    if not title:
        raise ResolveError("Spotify-Seite ohne og:title - Showtitel nicht lesbar")
    author = None
    desc = _meta(page, "og:description") or ""
    parts = [p.strip() for p in desc.split("·")]
    if len(parts) >= 3 and parts[0].lower() == "podcast" and parts[1]:
        author = parts[1]
    return title, author


def _norm(text):
    return " ".join((text or "").split()).casefold()


def is_same_show(title, author, result):
    """Exact (case/whitespace-insensitive) title; same author when Spotify names one."""
    if _norm(result.get("collectionName")) != _norm(title):
        return False
    if author and _norm(result.get("artistName")) != _norm(author):
        return False
    return True


def resolve_url(url, http):
    kind, value = classify(url)
    if kind == "feed":
        return Found(feed_url=value)

    if kind == "apple":
        data = json.loads(http(lookup_url(value)))
        hits = [r for r in data.get("results", []) if r.get("feedUrl")]
        if not hits:
            raise ResolveError(NO_FEED)
        return Found(hits[0]["feedUrl"], hits[0].get("collectionName"), hits[0].get("artistName"), "apple")

    title, author = spotify_show(http(spotify_url(value)))
    data = json.loads(http(search_url(title)))
    hits = [r for r in data.get("results", []) if is_same_show(title, author, r) and r.get("feedUrl")]
    feeds = sorted({r["feedUrl"] for r in hits})
    if not feeds:
        raise ResolveError(f"{NO_FEED} (Spotify-Titel: {title!r}"
                           + (f", Autor: {author!r}" if author else "") + ")")
    if len(feeds) > 1:
        raise ResolveError(f"Titel {title!r} ist mehrdeutig ({len(feeds)} Feeds: {', '.join(feeds)}); "
                           "Feed-URL direkt angeben")
    return Found(feeds[0], title, author, "spotify")
