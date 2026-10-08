import hashlib
import io
from pathlib import Path

import pytest

from transcribe import cli, feed, markdown, pipeline, publisher
from transcribe import queue as q

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FEED_URL = "https://feeds.example.org/transcripts"


def show():
    return feed.parse_feed((FIXTURES / "feed-transcripts.xml").read_bytes(), FEED_URL)


def ep(guid):
    return next(e for e in show().episodes if e.guid == guid)


# ---------- feed parsing ----------
def test_all_transcript_tags_are_parsed_with_attributes():
    ts = ep("t-vtt").transcripts
    assert [(t.url, t.type, t.language, t.rel) for t in ts] == [
        ("https://pub.example.org/1.txt", "text/plain", None, None),
        ("https://pub.example.org/1.vtt", "text/vtt", "en", "captions"),
    ]
    assert ep("t-none").transcripts == []


# ---------- preference ----------
@pytest.mark.parametrize("guid,url", [
    ("t-vtt", "https://pub.example.org/1.vtt"),        # vtt beats plain although listed second
    ("t-srt", "https://pub.example.org/2.srt"),
    ("t-html-plain", "https://pub.example.org/3.txt"),  # plain beats html although listed second
    ("t-html", "https://pub.example.org/4.html"),
])
def test_preference_order(guid, url):
    assert publisher.choose(ep(guid).transcripts).url == url


@pytest.mark.parametrize("guid", ["t-json", "t-none", "t-unsafe"])
def test_json_only_none_or_unsafe_url_falls_back_to_asr(guid):
    assert publisher.choose(ep(guid).transcripts) is None


def test_type_parameters_and_case_are_ignored():
    t = feed.Transcript("https://x/a", "Text/VTT; charset=utf-8", None, None)
    assert publisher.choose([t]) is t


def test_counter_proof_preference_order_is_load_bearing(monkeypatch):
    """Rank every type the same: the 'vtt beats plain' case must then fail."""
    monkeypatch.setattr(publisher, "RANK", {k: 0 for k in publisher.RANK})
    with pytest.raises(AssertionError):
        test_preference_order("t-vtt", "https://pub.example.org/1.vtt")


# ---------- formats ----------
def test_vtt_cues_keep_timestamps_and_drop_tags_and_notes():
    segs = publisher.parse_cues((FIXTURES / "transcript.vtt").read_text())
    assert [(s["start"], s["text"]) for s in segs] == [
        (0.0, "Welcome to the show."), (4.5, "Today: regions and availability zones."),
        (62.25, "A new topic starts here.")]


def test_srt_with_crlf_and_hours():
    segs = publisher.parse_cues((FIXTURES / "transcript.srt").read_bytes().decode())
    assert [(s["start"], s["end"], s["text"]) for s in segs] == [
        (0.0, 3.0, "Hello from SRT."), (3600.5, 3602.0, "One hour in.")]


def test_plain_one_paragraph_per_line_with_crlf():
    paras = publisher.parse_plain((FIXTURES / "transcript-lines.txt").read_bytes().decode())
    assert paras == ["First paragraph, one line.", "Second paragraph — with a dash.", "Third paragraph."]


def test_plain_hard_wrapped_blocks_are_joined():
    paras = publisher.parse_plain((FIXTURES / "transcript-blocks.txt").read_text())
    assert paras == ["A hard-wrapped first paragraph.", "Second paragraph also wrapped."]


def test_html_tags_stripped_scripts_and_styles_dropped():
    paras = publisher.parse_html((FIXTURES / "transcript.html").read_text())
    assert paras == ["Episode 4", "First & bold paragraph.", "Second", "line.", "Third"]


def test_parse_dispatches_by_type():
    vtt = (FIXTURES / "transcript.vtt").read_bytes()
    assert "segments" in publisher.parse(vtt, "text/vtt")
    assert publisher.parse(b"A.\nB.\n", "text/plain") == {"paragraphs": ["A.", "B."]}
    with pytest.raises(publisher.TranscriptError):
        publisher.parse(b"WEBVTT\n\n", "text/vtt")      # no cues -> refuse, do not write empty output
    with pytest.raises(publisher.TranscriptError):
        publisher.parse(b"{}", "application/json")


# ---------- pipeline ----------
class ExplodingBackend:
    name, model = "boom", "none"

    def transcribe(self, *a):
        raise AssertionError("ASR must not run when a publisher transcript is used")


def job_for(guid, tmp_path, language="en"):
    s, e = show(), ep(guid)
    return cli.job_from_episode(s, e, tmp_path / "out", language)


def fake_get(files):
    calls = []

    def get(url):
        calls.append(url)
        return files[url]
    get.calls = calls
    return get


def test_publisher_plain_writes_unstamped_paragraphs_and_no_audio(tmp_path):
    body = (FIXTURES / "transcript-lines.txt").read_bytes()
    get = fake_get({"https://pub.example.org/3.txt": body})
    j = job_for("t-html-plain", tmp_path)
    t = publisher.choose(j.transcripts)
    res = pipeline.process_publisher(j, t, ui=pipeline.Silent(), get=get)
    assert get.calls == ["https://pub.example.org/3.txt"]  # no audio download
    out = Path(res["output"])
    fm = markdown.read_frontmatter(out)
    assert fm["backend"] == "publisher-transcript" and fm["model"] is None
    assert fm["transcript_url"] == "https://pub.example.org/3.txt"
    assert fm["transcript_type"] == "text/plain"
    assert fm["transcript_sha256"] == hashlib.sha256(body).hexdigest() == res["transcript_sha256"]
    assert fm["audio_url"] is None and fm["audio_sha256"] is None and fm["audio_seconds"] is None
    assert fm["title_verified"] is False and fm["use"] == "personal-only"
    text = out.read_text()
    assert "Transkript des Herausgebers, nicht von uns erzeugt, ungeprüft" in text
    assert "\n\nFirst paragraph, one line.\n\nSecond paragraph" in text
    assert "[00:00]" not in text
    assert not markdown.segments_path(out).exists()
    assert not (tmp_path / "cache").exists()


def test_publisher_vtt_keeps_stamps(tmp_path):
    get = fake_get({"https://pub.example.org/1.vtt": (FIXTURES / "transcript.vtt").read_bytes()})
    j = job_for("t-vtt", tmp_path)
    res = pipeline.process_publisher(j, publisher.choose(j.transcripts), ui=pipeline.Silent(), get=get)
    text = Path(res["output"]).read_text()
    assert "[00:00] Welcome to the show." in text and "[01:02] A new topic starts here." in text
    assert markdown.read_frontmatter(res["output"])["language"] == "en"
    assert markdown.segments_path(res["output"]).exists()


def test_publisher_output_replaces_a_stale_segments_file(tmp_path):
    j = job_for("t-html-plain", tmp_path)
    stale = markdown.segments_path(pipeline.output_for(j))
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    pipeline.process_publisher(j, publisher.choose(j.transcripts), ui=pipeline.Silent(),
                               get=fake_get({"https://pub.example.org/3.txt": b"x\n"}))
    assert not stale.exists()


def test_render_refuses_publisher_with_model_or_audio_hash():
    meta = {f: None for f in markdown.FIELDS}
    meta.update(title="t", title_verified=False, backend="publisher-transcript", transcript_sha256="ab",
                source_tier="hypothesis", use="personal-only")
    assert markdown.render(meta, paragraphs_plain=["x"])
    with pytest.raises(ValueError):
        markdown.render({**meta, "model": "small"}, paragraphs_plain=["x"])
    with pytest.raises(ValueError):
        markdown.render({**meta, "audio_sha256": "cd"}, paragraphs_plain=["x"])
    with pytest.raises(ValueError):
        markdown.render({**meta, "transcript_sha256": None}, paragraphs_plain=["x"])


# ---------- CLI: source choice, --asr, notice ----------
def cli_env(monkeypatch, tmp_path, files):
    conf = tmp_path / "config"
    conf.write_text(f"STATE_FILE={tmp_path}/q.json\nOUT_DIR={tmp_path}/out\nCACHE_DIR={tmp_path}/cache\n")
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(conf))
    calls = []

    def get(url):
        calls.append(url)
        if url == FEED_URL:
            return (FIXTURES / "feed-transcripts.xml").read_bytes()
        return files[url]
    monkeypatch.setattr(cli.net, "get", get)
    return calls


def test_one_uses_publisher_and_notice_comes_before_the_transcript_download(monkeypatch, capsys, tmp_path):
    calls = cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": b"Hello.\n"})
    monkeypatch.setattr(cli, "Backends", lambda cfg: pytest.fail("no model may be loaded"))
    assert cli.main(["one", FEED_URL, "t-html-plain", "--yes"]) == 0
    err = capsys.readouterr().err
    assert calls == [FEED_URL, "https://pub.example.org/3.txt"]
    assert err.index("nur für den persönlichen Gebrauch") < err.index("GET https://pub.example.org/3.txt")
    assert "(c) 2025 Transcript Media" in err
    assert "* Transkript des Herausgebers laden - kein Audio-Download nötig\n  > GET https://pub.example.org/3.txt" in err


def test_one_without_yes_and_terminal_downloads_no_transcript(monkeypatch, capsys, tmp_path):
    calls = cli_env(monkeypatch, tmp_path, {})
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["one", FEED_URL, "t-html-plain"]) == 1
    assert calls == [FEED_URL]


def test_asr_flag_forces_whisper(monkeypatch, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    used = {}

    def fake_run_one(job, cfg, model):
        used["asr"] = True
    monkeypatch.setattr(cli, "run_one", fake_run_one)
    monkeypatch.setattr(cli.pipeline, "process_publisher", lambda *a, **k: pytest.fail("publisher used"))
    assert cli.main(["one", FEED_URL, "t-html-plain", "--asr", "--yes"]) == 0
    assert used == {"asr": True}


def test_no_transcript_falls_back_to_whisper(monkeypatch, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    used = {}
    monkeypatch.setattr(cli, "run_one", lambda job, cfg, model: used.setdefault("asr", True))
    assert cli.main(["one", FEED_URL, "t-json", "--yes"]) == 0
    assert used == {"asr": True}


# ---------- queue ----------
def test_queue_records_backend_and_is_idempotent_for_publisher_entries(monkeypatch, capsys, tmp_path):
    calls = cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": b"Hello.\n",
                                            "https://pub.example.org/4.html": b"<p>Hi</p>"})
    monkeypatch.setattr(cli, "Backends", lambda cfg: pytest.fail("no model may be loaded"))
    monkeypatch.setattr(cli.pipeline, "check_tools", lambda ui: pytest.fail("no ffmpeg needed"))
    assert cli.main(["queue", "add", FEED_URL, "--range", "3-4", "--yes"]) == 0
    assert cli.main(["queue", "run"]) == 0
    state = q.Queue(tmp_path / "q.json")
    entries = [state.get(q.key(FEED_URL, g)) for g in ("t-html-plain", "t-html")]
    assert [e["status"] for e in entries] == ["done", "done"]
    assert [e["backend"] for e in entries] == ["publisher-transcript"] * 2
    assert entries[0]["transcript_sha256"] == hashlib.sha256(b"Hello.\n").hexdigest()
    n = len(calls)
    capsys.readouterr()
    assert cli.main(["queue", "run"]) == 0
    assert len(calls) == n and "Nichts zu tun" in capsys.readouterr().err
    # publisher text changed on disk -> redo, judged by transcript_sha256
    out = entries[0]["output"]
    Path(out).write_text(Path(out).read_text().replace(entries[0]["transcript_sha256"], "ff" * 32))
    assert cli.main(["queue", "run"]) == 0
    assert calls[n:] == ["https://pub.example.org/3.txt"]


def test_queue_add_asr_is_recorded_and_honoured(monkeypatch, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    assert cli.main(["queue", "add", FEED_URL, "--range", "3", "--asr", "--yes"]) == 0
    e = q.Queue(tmp_path / "q.json").get(q.key(FEED_URL, "t-html-plain"))
    assert e["force_asr"] is True
    assert cli.source_for(e["transcripts"], force_asr=e["force_asr"]) is None
    assert cli.source_for(e["transcripts"], force_asr=False).url == "https://pub.example.org/3.txt"


def test_publisher_done_entry_validity_uses_transcript_sha(tmp_path):
    out = tmp_path / "o.md"
    out.write_text('---\naudio_sha256: null\ntranscript_sha256: "aa"\n---\n')
    base = {"output": str(out), "backend": "publisher-transcript", "transcript_sha256": "aa", "audio_sha256": None}
    assert q.output_is_valid(base)
    assert not q.output_is_valid({**base, "transcript_sha256": "bb"})


def test_list_marks_usable_publisher_transcripts(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    cli.main(["list", FEED_URL])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].endswith("VTT and plain  [Transkript: text/vtt]")
    assert lines[4].endswith("JSON only")
