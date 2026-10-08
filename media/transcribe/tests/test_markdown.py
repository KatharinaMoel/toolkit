from pathlib import Path

import pytest

from transcribe import markdown


@pytest.mark.parametrize("text,slug", [
    ("Episode 1: Welcome & Why It Matters", "episode-1-welcome-why-it-matters"),
    ("Grüße aus Köln – Straße", "gruesse-aus-koeln-strasse"),
    ("AWS Support Plans (Basic → Enterprise)", "aws-support-plans-basic-enterprise"),
    ("☁️", "untitled"),
    ("", "untitled"),
])
def test_slugify(text, slug):
    assert markdown.slugify(text) == slug


def test_slug_is_bounded_and_does_not_end_with_dash():
    slug = markdown.slugify("word " * 40)
    assert len(slug) <= 60 and not slug.endswith("-")


@pytest.mark.parametrize("seconds,text", [(0, "00:00"), (59.9, "00:59"), (61, "01:01"), (3723, "62:03")])
def test_stamp(seconds, text):
    assert markdown.stamp(seconds) == text


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_paragraphs_group_about_a_minute_and_prefer_sentence_ends():
    segs = [seg(i * 10, i * 10 + 10, f"Sentence {i}.") for i in range(13)]  # 0..130 s
    paras = markdown.paragraphs(segs)
    assert [p[0] for p in paras] == [0, 60, 120]
    assert paras[0][1].startswith("Sentence 0. Sentence 1.")


def test_paragraph_waits_for_sentence_end_but_not_forever():
    # no punctuation at all -> forced break at the hard limit (90 s)
    segs = [seg(i * 10, i * 10 + 10, f"word{i}") for i in range(20)]
    starts = [p[0] for p in markdown.paragraphs(segs)]
    assert starts == [0, 90, 180]
    # the sentence ends in the segment at 70 s -> next paragraph starts at 80 s, not 60 s
    segs = [seg(i * 10, i * 10 + 10, "end." if i == 7 else "go") for i in range(10)]
    assert [p[0] for p in markdown.paragraphs(segs)] == [0, 80]


def test_paragraphs_skip_empty_text():
    assert markdown.paragraphs([seg(0, 1, "  "), seg(1, 2, " Hi.")]) == [(1, "Hi.")]


META = {
    "title": 'Episode 3: Inside the Exam "quoted"', "title_verified": False, "show": "Show",
    "feed_url": "https://f", "episode_guid": "g3", "episode_index": 3, "published": "2025-08-30T17:35:10-05:00",
    "audio_url": "https://a/3.mp3", "audio_sha256": "ab" * 32, "audio_bytes": 18207151, "audio_seconds": 1234.5,
    "transcript_url": None, "transcript_type": None, "transcript_sha256": None,
    "copyright": "(c) 2025 X", "backend": "faster-whisper", "model": "small", "language": "en",
    "transcribed_at": "2026-10-08T10:00:00Z", "tool_version": "0.1.0",
    "source_tier": "hypothesis", "use": "personal-only",
}


def test_render_has_all_frontmatter_fields_in_order_and_round_trips(tmp_path):
    text = markdown.render(META, [seg(0, 5, " Hello there."), seg(65, 70, "Next part.")])
    head = text.split("---\n")[1]
    keys = [line.split(":", 1)[0] for line in head.splitlines()]
    assert keys == list(markdown.FIELDS)
    path = tmp_path / "x.md"
    path.write_text(text)
    assert markdown.read_frontmatter(path) == META


def test_render_body_marks_transcript_unchecked_and_title_unverified():
    text = markdown.render(META, [seg(0, 5, "Hello there."), seg(65, 70, "Next part.")])
    body = text.split("---\n", 2)[2]
    assert "unchecked" in body and "not verified" in body
    assert "[00:00] Hello there." in body and "[01:05] Next part." in body


def test_render_refuses_missing_or_verified_title():
    with pytest.raises(ValueError):
        markdown.render({k: v for k, v in META.items() if k != "audio_sha256"}, [])
    with pytest.raises(ValueError):
        markdown.render({**META, "title_verified": True}, [])
    with pytest.raises(ValueError):
        markdown.render({**META, "use": "public"}, [])


def test_output_path():
    p = markdown.output_path(Path("/out"), "My Show!", 7, "Episode 7: Hi")
    assert p == Path("/out/my-show/007-episode-7-hi.md")
    assert markdown.segments_path(p) == Path("/out/my-show/007-episode-7-hi.segments.json")
