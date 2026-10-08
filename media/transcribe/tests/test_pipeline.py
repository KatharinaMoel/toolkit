import hashlib
import json
import sys
import types
import wave
from pathlib import Path

import pytest

from transcribe import backend, markdown, pipeline


def write_wav(path, seconds=2.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))


class FakeBackend:
    name = "fake"
    model = "tiny"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def transcribe(self, wav_path, language):
        self.calls.append((Path(wav_path).suffix, language))
        if self.fail:
            raise RuntimeError("decoder exploded")
        segs = [{"start": 0.0, "end": 4.0, "text": " Global infrastructure."},
                {"start": 61.0, "end": 64.0, "text": " Regions and zones."}]
        return segs, {"language": "en", "duration": 64.0}


def fake_fetch(payload=b"ID3fakeaudio"):
    def fetch(url, dest, ui):
        dest.write_bytes(payload)
    return fetch


def fake_normalise(src, dst, ui):
    write_wav(dst, seconds=125.0)


def job(tmp_path, **kw):
    base = dict(
        show="Example Exam Prep Podcast", feed_url="https://feeds.example.org/x", guid="guid-003",
        index=3, title="Episode 3: Inside the Exam", published="2025-08-30T17:35:10-05:00",
        audio_url="https://media.example.org/ep3.mp3", copyright="(c) 2025 Example Media",
        out_dir=tmp_path / "out", language="en")
    base.update(kw)
    return pipeline.Job(**base)


def settings(tmp_path, keep=False):
    return pipeline.Settings(cache_dir=tmp_path / "cache", keep_audio=keep)


def test_episode_end_to_end(tmp_path):
    be = FakeBackend()
    res = pipeline.process(job(tmp_path), settings(tmp_path), be, ui=pipeline.Silent(),
                           fetch=fake_fetch(), normalise=fake_normalise)
    out = Path(res["output"])
    assert out == tmp_path / "out/example-exam-prep-podcast/003-episode-3-inside-the-exam.md"
    fm = markdown.read_frontmatter(out)
    assert fm["title"] == "Episode 3: Inside the Exam"
    assert fm["title_verified"] is False
    assert fm["audio_sha256"] == hashlib.sha256(b"ID3fakeaudio").hexdigest() == res["audio_sha256"]
    assert fm["audio_seconds"] == 125.0
    assert fm["backend"] == "fake" and fm["model"] == "tiny" and fm["language"] == "en"
    assert fm["source_tier"] == "hypothesis" and fm["use"] == "personal-only"
    assert fm["copyright"] == "(c) 2025 Example Media"
    assert "[01:01] Regions and zones." in out.read_text()
    segs = json.loads(markdown.segments_path(out).read_text())
    assert segs["segments"][0]["text"] == " Global infrastructure."
    assert be.calls == [(".wav", "en")]
    # audio removed after success by default
    assert list((tmp_path / "cache").iterdir()) == []


def test_keep_audio(tmp_path):
    pipeline.process(job(tmp_path), settings(tmp_path, keep=True), FakeBackend(), ui=pipeline.Silent(),
                     fetch=fake_fetch(), normalise=fake_normalise)
    suffixes = sorted(p.suffix for p in (tmp_path / "cache").iterdir())
    assert suffixes == [".mp3", ".wav"]


def test_language_auto_is_passed_as_none(tmp_path):
    be = FakeBackend()
    pipeline.process(job(tmp_path, language="auto"), settings(tmp_path), be, ui=pipeline.Silent(),
                     fetch=fake_fetch(), normalise=fake_normalise)
    assert be.calls == [(".wav", None)]


def test_backend_failure_writes_no_output_and_keeps_download(tmp_path):
    with pytest.raises(RuntimeError):
        pipeline.process(job(tmp_path), settings(tmp_path), FakeBackend(fail=True), ui=pipeline.Silent(),
                         fetch=fake_fetch(), normalise=fake_normalise)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.md"))
    assert [p.suffix for p in (tmp_path / "cache").iterdir()] == [".mp3"]


def test_cached_download_is_reused(tmp_path):
    calls = []

    def fetch(url, dest, ui):
        calls.append(url)
        dest.write_bytes(b"x")
    s = settings(tmp_path, keep=True)
    for _ in range(2):
        pipeline.process(job(tmp_path), s, FakeBackend(), ui=pipeline.Silent(),
                         fetch=fetch, normalise=fake_normalise)
    assert len(calls) == 1


def test_local_file_is_never_deleted(tmp_path):
    audio = tmp_path / "talk.m4a"
    audio.write_bytes(b"local audio")
    j = pipeline.file_job(str(audio), tmp_path / "out", "en")
    res = pipeline.process(j, settings(tmp_path), FakeBackend(), ui=pipeline.Silent(),
                           fetch=fake_fetch(), normalise=fake_normalise)
    assert audio.exists()
    assert Path(res["output"]).parent == tmp_path / "out/files"
    assert Path(res["output"]).name.startswith("talk-")
    fm = markdown.read_frontmatter(Path(res["output"]))
    assert fm["title"] == "talk" and fm["feed_url"] is None and fm["episode_index"] is None


def test_file_job_refuses_missing_path(tmp_path):
    with pytest.raises(pipeline.PipelineError):
        pipeline.file_job(str(tmp_path / "nope.mp3"), tmp_path, "en")


def test_package_import_does_not_need_faster_whisper():
    assert "faster_whisper" not in sys.modules


def test_faster_whisper_backend_uses_the_documented_calls(monkeypatch):
    seen = {}

    class Seg:
        def __init__(self, i):
            self.id, self.start, self.end, self.text = i, float(i), i + 1.0, f" t{i}"
            self.avg_logprob, self.no_speech_prob, self.compression_ratio, self.temperature = -0.2, 0.01, 1.3, 0.0

    class Model:
        def __init__(self, model, **kw):
            seen["init"] = (model, kw)

        def transcribe(self, audio, **kw):
            seen["transcribe"] = (audio, kw)
            info = types.SimpleNamespace(language="en", language_probability=0.99, duration=2.0)
            return iter([Seg(0), Seg(1)]), info

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = Model
    fake.__version__ = "1.2.1"
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    be = backend.FasterWhisper("small", cpu_threads=16)
    segs, info = be.transcribe("/tmp/a.wav", "en")
    assert seen["init"] == ("small", {"device": "auto", "compute_type": "int8", "cpu_threads": 16})
    assert seen["transcribe"] == ("/tmp/a.wav", {"language": "en", "beam_size": 5})
    assert [s["text"] for s in segs] == [" t0", " t1"]
    assert info["language"] == "en" and info["duration"] == 2.0
    assert be.name == "faster-whisper"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "/etc/passwd", "ftp://x/a.mp3"])
def test_feed_enclosure_must_be_http(tmp_path, url):
    with pytest.raises(pipeline.PipelineError, match="http"):
        pipeline.process(job(tmp_path, audio_url=url), settings(tmp_path), FakeBackend(), ui=pipeline.Silent(),
                         fetch=fake_fetch(), normalise=fake_normalise)


def test_outputs_follow_the_umask_not_mkstemp_0600(tmp_path):
    import os
    old = os.umask(0o022)
    try:
        res = pipeline.process(job(tmp_path), settings(tmp_path), FakeBackend(), ui=pipeline.Silent(),
                               fetch=fake_fetch(), normalise=fake_normalise)
    finally:
        os.umask(old)
    assert Path(res["output"]).stat().st_mode & 0o777 == 0o644
    assert markdown.segments_path(res["output"]).stat().st_mode & 0o777 == 0o644
