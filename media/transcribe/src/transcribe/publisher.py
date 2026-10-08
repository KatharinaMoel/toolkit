"""Publisher transcripts (<podcast:transcript>): preferred over our own ASR.

When a show publishes its own transcript it is usually the original script,
so it is more accurate than any recognition and costs seconds instead of
minutes - and no audio needs to be downloaded at all.

Preference: text/vtt or application/x-subrip (they keep timestamps), then
text/plain, then text/html (tags stripped). application/json is skipped: the
tool has no verified sample of that format, so it falls back to ASR instead
of guessing.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

RANK = {"text/vtt": 0, "application/x-subrip": 0, "text/plain": 1, "text/html": 2}
TIMED = ("text/vtt", "application/x-subrip")


class TranscriptError(Exception):
    pass


def base_type(mime):
    return (mime or "").split(";", 1)[0].strip().lower()


def choose(transcripts):
    """The best usable transcript, or None (-> ASR). Only http(s) URLs count."""
    usable = [(RANK[base_type(t.type)], pos, t) for pos, t in enumerate(transcripts)
              if base_type(t.type) in RANK and urlparse(t.url).scheme in ("http", "https")]
    return min(usable, key=lambda u: (u[0], u[1]))[2] if usable else None


_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
_TAG = re.compile(r"<[^>]+>")


def _secs(h, m, s, frac):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def parse_cues(text):
    """WebVTT or SRT cues -> [{start, end, text}]; NOTE/STYLE blocks and tags dropped."""
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            m = _CUE.match(line)
            if m:
                words = " ".join(_TAG.sub("", ln).strip() for ln in lines[i + 1:])
                words = " ".join(words.split())
                if words:
                    segments.append({"start": round(_secs(*m.groups()[:4]), 3),
                                     "end": round(_secs(*m.groups()[4:]), 3), "text": words})
                break
    return segments


def parse_plain(text):
    """Paragraphs from plain text.

    Blank lines always separate paragraphs. Inside a block, a line that ends a
    sentence also ends the paragraph (publishers often write one paragraph per
    line); other line breaks are hard wraps and are joined.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        current = []
        for line in block.split("\n"):
            line = " ".join(line.split())
            if not line:
                continue
            current.append(line)
            if line.endswith((".", "?", "!", '"', "\u201d", "'", ")")):
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
    return paragraphs


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [[]], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append([])

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append([])

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append([])

    def handle_data(self, data):
        if not self.skip:
            self.parts[-1].append(data)


def parse_html(text):
    p = _Text()
    p.feed(text)
    p.close()
    return [t for t in (" ".join("".join(part).split()) for part in p.parts) if t]


def parse(data, mime):
    """-> {"segments": [...]} for timed formats, {"paragraphs": [...]} otherwise."""
    kind = base_type(mime)
    if kind not in RANK:
        raise TranscriptError(f"Transkript-Typ {mime!r} wird nicht gelesen")
    text = data.decode("utf-8", "replace").lstrip("﻿")
    if kind in TIMED:
        result = {"segments": parse_cues(text)}
    elif kind == "text/html":
        result = {"paragraphs": parse_html(text)}
    else:
        result = {"paragraphs": parse_plain(text)}
    if not next(iter(result.values())):
        raise TranscriptError(f"Transkript ({mime}) enthält keinen Text")
    return result
