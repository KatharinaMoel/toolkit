"""RSS podcast feed parsing.

Episode numbers are this tool's own: chronological, oldest = 1, so they stay
stable when a show publishes new episodes. Feed titles are kept verbatim and
treated as unverified metadata - they can be wrong.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
PODCAST = "{https://podcastindex.org/namespace/1.0}"


class FeedError(Exception):
    pass


@dataclass
class Transcript:
    """One <podcast:transcript> of an item (podcastindex namespace)."""
    url: str
    type: str
    language: str | None
    rel: str | None


@dataclass
class Episode:
    index: int
    guid: str
    title: str
    published: str | None
    duration_seconds: int | None
    audio_url: str | None
    audio_length: int | None
    transcripts: list = field(default_factory=list)


@dataclass
class Show:
    title: str
    feed_url: str
    copyright: str | None
    license: str | None
    episodes: list = field(default_factory=list)


def parse_duration(raw):
    """itunes:duration as seconds: '1134', '18:22', '1:02:03'; None if unreadable."""
    if not raw or not re.fullmatch(r"\d+(:\d{1,2}){0,2}", raw.strip()):
        return None
    seconds = 0
    for part in raw.strip().split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def _text(el, tag):
    found = el.find(tag)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _date(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def parse_feed(data, feed_url):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError(f"kein gültiges XML unter {feed_url}: {exc}") from None
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedError(f"{feed_url} ist kein RSS-Feed (Wurzelelement <{root.tag}>)")

    raw = []
    for pos, item in enumerate(channel.findall("item")):
        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else None
        length = enclosure.get("length") if enclosure is not None else None
        guid = _text(item, "guid") or audio_url
        if not guid:
            continue  # neither guid nor audio: nothing to identify or transcribe
        when = _date(_text(item, "pubDate"))
        transcripts = [Transcript(t.get("url").strip(), (t.get("type") or "").strip(), t.get("language"), t.get("rel"))
                       for t in item.findall(f"{PODCAST}transcript") if (t.get("url") or "").strip()]
        raw.append((when, pos, Episode(
            index=0, guid=guid, title=_text(item, "title") or "(ohne Titel)",
            published=when.isoformat() if when else None,
            duration_seconds=parse_duration(_text(item, f"{ITUNES}duration")),
            audio_url=audio_url or None,
            audio_length=int(length) if length and length.isdigit() else None,
            transcripts=transcripts)))

    # oldest first; undated items after dated ones; ties keep feed order
    raw.sort(key=lambda r: (r[0] is None, r[0].timestamp() if r[0] else 0, r[1]))
    episodes = []
    for i, (_, _, ep) in enumerate(raw, 1):
        ep.index = i
        episodes.append(ep)

    return Show(
        title=_text(channel, "title") or "(ohne Titel)",
        feed_url=feed_url,
        copyright=_text(channel, "copyright"),
        license=_text(channel, f"{PODCAST}license"),
        episodes=episodes,
    )


def select(show, ref):
    """An episode by our index ('7') or by guid; refuses audio-less items."""
    ref = str(ref).strip()
    if ref.isdigit():
        match = [e for e in show.episodes if e.index == int(ref)]
    else:
        match = [e for e in show.episodes if e.guid == ref]
    if not match:
        raise FeedError(f"Episode {ref!r} ist nicht im Feed ({len(show.episodes)} Episoden; "
                        f"'transcribe list <feed>' zeigt die Nummern)")
    if not match[0].audio_url:
        raise FeedError(f"Episode {ref!r} hat kein Audio im Feed (kein <enclosure>)")
    return match[0]


def parse_range(spec, count):
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", spec.strip())
    if not m:
        raise FeedError(f"Bereich {spec!r} nicht lesbar - erwartet z.B. 1-10 oder 7")
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    if lo < 1 or hi < lo or hi > count:
        raise FeedError(f"Bereich {spec!r} passt nicht zu {count} Episoden")
    return list(range(lo, hi + 1))
