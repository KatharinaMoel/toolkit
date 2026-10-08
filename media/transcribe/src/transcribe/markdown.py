"""Slugs, paragraph stamping, and the Markdown transcript format."""

import json
import re
import unicodedata
from pathlib import Path

# Frontmatter fields, in this order. Values are written as JSON scalars,
# which are also valid YAML, so any frontmatter reader can parse them.
FIELDS = (
    "title", "title_verified", "show", "feed_url", "episode_guid", "episode_index", "published",
    "audio_url", "audio_sha256", "audio_bytes", "audio_seconds", "transcript_url", "transcript_type", "transcript_sha256",
    "copyright", "backend", "model", "language",
    "transcribed_at", "tool_version", "source_tier", "use",
)

NOTE = ("> Automatic transcript ({backend} {model}), unchecked. The title comes from the feed "
        "and was not verified against the audio. Personal use only.")
PUBLISHER = "publisher-transcript"
PUBLISHER_NOTE = ("> Transkript des Herausgebers, nicht von uns erzeugt, ungeprüft. The title comes from "
                  "the feed and was not verified against the content. Personal use only.")

PARAGRAPH_TARGET = 60   # seconds: start looking for a sentence end
PARAGRAPH_HARD = 90     # seconds: break here even mid-sentence
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def slugify(text, max_len=60):
    ascii_text = unicodedata.normalize("NFKD", text.translate(_UMLAUTS)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0] if "-" in slug[:max_len] else slug[:max_len]
    return slug.strip("-") or "untitled"


def stamp(seconds):
    """[mm:ss]; minutes keep counting past 59 so stamps stay one format."""
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def paragraphs(segments, target=PARAGRAPH_TARGET, hard=PARAGRAPH_HARD):
    """Group segments into ~1-minute paragraphs: [(start_seconds, text), ...]."""
    out, start, parts, last = [], None, [], ""
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if start is not None:
            elapsed = seg["start"] - start
            if (elapsed >= target and last.endswith((".", "?", "!"))) or elapsed >= hard:
                out.append((start, " ".join(parts)))
                start, parts = None, []
        if start is None:
            start = seg["start"]
        parts.append(text)
        last = text
    if parts:
        out.append((start, " ".join(parts)))
    return out


def _check(meta):
    missing = [f for f in FIELDS if f not in meta]
    if missing:
        raise ValueError(f"frontmatter fields missing: {missing}")
    if meta["title_verified"] is not False:
        raise ValueError("feed titles are never verified by this tool")
    if meta["use"] != "personal-only" or meta["source_tier"] != "hypothesis":
        raise ValueError("transcripts are personal-only hypotheses")
    if meta["backend"] == PUBLISHER:
        if meta["model"] is not None or meta["audio_sha256"] is not None or not meta["transcript_sha256"]:
            raise ValueError("publisher transcripts: model and audio_sha256 null, transcript_sha256 required")
    elif not meta["audio_sha256"]:
        raise ValueError("ASR transcripts need audio_sha256")


def render(meta, segments=None, paragraphs_plain=None):
    """Stamped paragraphs from timed segments, or unstamped paragraphs from plain text."""
    _check(meta)
    head = "\n".join(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}" for k in FIELDS)
    if meta["backend"] == PUBLISHER:
        body = [PUBLISHER_NOTE]
    else:
        body = [NOTE.format(backend=meta["backend"], model=meta["model"])]
    if paragraphs_plain is not None:
        body += list(paragraphs_plain)
    else:
        body += [f"[{stamp(start)}] {text}" for start, text in paragraphs(segments or [])]
    return f"---\n{head}\n---\n\n" + "\n\n".join(body) + "\n"


def read_frontmatter(path):
    """Read back what render() wrote (JSON-scalar `key: value` lines)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(":")
        try:
            meta[key.strip()] = json.loads(value.strip())
        except json.JSONDecodeError:
            meta[key.strip()] = value.strip()
    return meta


def output_path(out_dir, show_title, index, title):
    return Path(out_dir) / slugify(show_title) / f"{index:03d}-{slugify(title)}.md"


def segments_path(md_path):
    md_path = Path(md_path)
    return md_path.with_name(md_path.stem + ".segments.json")
