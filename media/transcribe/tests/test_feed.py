from pathlib import Path

import pytest

from transcribe import feed

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FEED_URL = "https://feeds.example.org/exam-prep"


def load(name="feed.xml"):
    return feed.parse_feed((FIXTURES / name).read_bytes(), FEED_URL)


def test_channel_metadata():
    show = load()
    assert show.title == "Example Exam Prep Podcast"
    assert show.copyright == "(c) 2025 Example Media"
    assert show.license == "cc-by-nc-4.0"
    assert show.feed_url == FEED_URL
    assert len(show.episodes) == 5


def test_indices_are_chronological_oldest_first():
    show = load()
    assert [e.guid for e in show.episodes] == [
        "guid-001", "guid-002", "guid-003", "guid-noaudio", "guid-trailer"]
    assert [e.index for e in show.episodes] == [1, 2, 3, 4, 5]


def test_newest_first_feed_is_renumbered_and_guid_falls_back_to_enclosure():
    show = load("feed-newest-first.xml")
    assert [e.title for e in show.episodes] == ["First", "Second"]
    assert show.episodes[0].guid == "https://media.example.org/a.mp3"
    assert show.copyright is None


def test_episode_fields():
    ep = load().episodes[0]
    assert ep.title == "Episode 1: Welcome & Why It Matters"
    assert ep.audio_url == "https://media.example.org/ep1.mp3"
    assert ep.audio_length == 18207151
    assert ep.duration_seconds == 1134
    assert ep.published == "2025-08-30T17:34:03-05:00"


@pytest.mark.parametrize("raw,seconds", [
    ("1134", 1134), ("18:22", 1102), ("1:02:03", 3723), ("", None), ("abc", None), (None, None)])
def test_duration_formats(raw, seconds):
    assert feed.parse_duration(raw) == seconds


def test_wrong_title_is_kept_verbatim_never_corrected():
    # The feed title is metadata only; the parser must not "fix" or drop it.
    ep = load().episodes[2]
    assert ep.title == "Episode 3: Inside the Exam"


def test_missing_enclosure_is_listed_but_has_no_audio():
    ep = load().episodes[3]
    assert ep.guid == "guid-noaudio"
    assert ep.audio_url is None


def test_select_by_index_and_guid():
    show = load()
    assert feed.select(show, "2").guid == "guid-002"
    assert feed.select(show, "guid-trailer").index == 5


def test_select_refuses_unknown_and_audioless():
    show = load()
    with pytest.raises(feed.FeedError, match="nicht im Feed"):
        feed.select(show, "99")
    with pytest.raises(feed.FeedError, match="kein Audio"):
        feed.select(show, "4")


def test_parse_range():
    assert feed.parse_range("1-3", 10) == [1, 2, 3]
    assert feed.parse_range("7", 10) == [7]
    for bad in ("0-2", "3-1", "1-11", "x", "1-"):
        with pytest.raises(feed.FeedError):
            feed.parse_range(bad, 10)


def test_not_a_feed_is_refused():
    with pytest.raises(feed.FeedError):
        feed.parse_feed(b"<html><body>hi</body></html>", FEED_URL)
    with pytest.raises(feed.FeedError):
        feed.parse_feed(b"not xml at all", FEED_URL)
