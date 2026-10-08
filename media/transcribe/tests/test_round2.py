"""Fix round 2: retry limit for crashes, download limits, lock and --asr end to end,
publisher fallback, queue retry, audio_bytes, file-name collisions, small hardening."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from transcribe import cli, config, markdown, net, pipeline, publisher, resolve, ui
from transcribe import queue as q

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FEED_URL = "https://feeds.example.org/transcripts"


def entry(i):
    return {"feed_url": "https://f", "guid": f"g{i}", "index": i, "title": f"E{i}"}


# ---------- I1: crash recovery counts the attempt ----------
def test_crash_loop_ends_as_failed_after_max_attempts(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    worked = []
    for _ in range(q.MAX_ATTEMPTS + 3):  # each run "kills" the process mid-work
        state = q.Queue(path)
        state.recover()
        todo, _ = q.plan(state)
        worked.append(bool(todo))
        for k in todo:
            state.mark_running(k)
        state.save()
    e = q.Queue(path).get(q.key("https://f", "g1"))
    assert worked == [True] * q.MAX_ATTEMPTS + [False] * 3
    assert e["status"] == "failed"
    assert e["error"] == f"abgebrochen (Absturz/Kill) nach {q.MAX_ATTEMPTS} Versuchen"


def test_crash_below_limit_still_goes_back_to_pending(tmp_path):
    state = q.Queue(tmp_path / "q.json")
    state.add(entry(1))
    state.mark_running(q.key("https://f", "g1"))
    assert state.recover() == [q.key("https://f", "g1")]
    assert state.get(q.key("https://f", "g1"))["status"] == "pending"


# ---------- I2/I3: download limits ----------
def test_curl_command_has_globoff_stall_and_size_limits():
    cmd = pipeline.curl_command("https://m/a[1-2].mp3", Path("/c/x.part"), max_bytes=1024 * 1024 * 1024)
    assert cmd[0] == "curl" and cmd[-1] == "https://m/a[1-2].mp3"
    joined = " ".join(cmd)
    for flag in ("--globoff", "--speed-limit 1024", "--speed-time 60", "--max-filesize 1073741824",
                 "--proto =http,https", "--proto-redir =http,https", "-fL"):
        assert flag in joined


@pytest.mark.parametrize("code,needle", [(63, "MAX_AUDIO_MB=7"), (28, "1024 Bytes/s")])
def test_curl_refusals_name_the_limit(monkeypatch, tmp_path, code, needle):
    import subprocess

    def fail(cmd, check):
        raise subprocess.CalledProcessError(code, cmd)
    monkeypatch.setattr(pipeline.subprocess, "run", fail)
    with pytest.raises(pipeline.PipelineError, match=needle.replace("/", "/")):
        pipeline.curl_download("https://m/a.mp3", tmp_path / "a.mp3", ui.Silent(), max_bytes=7 * 1024 * 1024)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_net_get_caps_the_read(monkeypatch):
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda req, timeout: FakeResp(b"x" * 11))
    monkeypatch.setattr(net, "LIMIT_BYTES", 10)
    monkeypatch.setattr(net, "LIMIT_NAME", "MAX_TEXT_MB=0.00001")
    with pytest.raises(net.TooLarge, match="MAX_TEXT_MB"):
        net.get("https://x/feed")
    monkeypatch.setattr(net, "LIMIT_BYTES", 11)
    assert net.get("https://x/feed") == b"x" * 11


def test_size_limits_come_from_config(tmp_path):
    f = tmp_path / "c"
    f.write_text("MAX_AUDIO_MB=2048\nMAX_TEXT_MB=5\n")
    cfg = config.load(f, env={"HOME": "/h"})
    assert (cfg.max_audio_mb, cfg.max_text_mb) == (2048, 5)
    d = config.load(tmp_path / "none", env={"HOME": "/h"})
    assert (d.max_audio_mb, d.max_text_mb) == (1024, 50)
    f.write_text("MAX_AUDIO_MB=0\n")
    with pytest.raises(config.ConfigError):
        config.load(f, env={"HOME": "/h"})


# ---------- shared CLI fixture ----------
def cli_env(monkeypatch, tmp_path, files):
    conf = tmp_path / "config"
    conf.write_text(f"STATE_FILE={tmp_path}/q.json\nOUT_DIR={tmp_path}/out\nCACHE_DIR={tmp_path}/cache\n")
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(conf))
    calls = []

    def get(url):
        calls.append(url)
        if url == FEED_URL:
            return (FIXTURES / "feed-transcripts.xml").read_bytes()
        if isinstance(files.get(url), Exception):
            raise files[url]
        return files[url]
    monkeypatch.setattr(cli.net, "get", get)
    return calls


class FakeBackends:
    def __init__(self, cfg):
        pass

    def get(self, model):
        return "fake-backend"


def fake_asr(calls):
    def process(job, settings, backend, ui_):
        calls.append(job.guid)
        return {"output": "/dev/null", "backend": "faster-whisper", "audio_sha256": "aa", "audio_bytes": 3,
                "audio_seconds": 60.0, "compute_seconds": 6.0}
    return process


# ---------- I4: the lock is load-bearing ----------
def test_queue_run_is_refused_while_locked(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    with q.locked(path):
        with pytest.raises(q.QueueError, match="gesperrt"):
            q.run(path, lambda e: pytest.fail("must not work while locked"))
    assert q.Queue(path).get(q.key("https://f", "g1"))["status"] == "pending"


def test_queue_add_exits_1_while_locked(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    with q.locked(tmp_path / "q.json"):
        assert cli.main(["queue", "add", FEED_URL, "--range", "1", "--yes"]) == 1
    assert "gesperrt" in capsys.readouterr().err
    assert not (tmp_path / "q.json").exists()


# ---------- I5: --asr end to end through queue run ----------
def test_queue_run_asr_forces_whisper_end_to_end(monkeypatch, tmp_path):
    calls = cli_env(monkeypatch, tmp_path, {})
    asr = []
    monkeypatch.setattr(cli, "Backends", FakeBackends)
    monkeypatch.setattr(cli.pipeline, "check_tools", lambda ui_: None)
    monkeypatch.setattr(cli.pipeline, "process", fake_asr(asr))
    assert cli.main(["queue", "add", FEED_URL, "--range", "3", "--yes"]) == 0
    assert cli.main(["queue", "run", "--asr"]) == 0
    assert asr == ["t-html-plain"]
    assert calls == [FEED_URL]  # no transcript GET
    assert q.Queue(tmp_path / "q.json").get(q.key(FEED_URL, "t-html-plain"))["backend"] == "faster-whisper"


def test_queue_add_asr_is_honoured_by_run(monkeypatch, tmp_path):
    calls = cli_env(monkeypatch, tmp_path, {})
    asr = []
    monkeypatch.setattr(cli, "Backends", FakeBackends)
    monkeypatch.setattr(cli.pipeline, "check_tools", lambda ui_: None)
    monkeypatch.setattr(cli.pipeline, "process", fake_asr(asr))
    assert cli.main(["queue", "add", FEED_URL, "--range", "3", "--asr", "--yes"]) == 0
    assert cli.main(["queue", "run"]) == 0
    assert asr == ["t-html-plain"] and calls == [FEED_URL]


# ---------- I6: fallback within the same attempt ----------
@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError("https://pub.example.org/3.txt", 404, "Not Found", {}, None),
    urllib.error.URLError("timed out"),
    b"   \n",                      # empty
    net.TooLarge("zu groß"),
])
def test_publisher_failure_falls_back_to_asr_and_records_reason(monkeypatch, capsys, tmp_path, failure):
    calls = cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": failure})
    asr = []
    monkeypatch.setattr(cli, "Backends", FakeBackends)
    monkeypatch.setattr(cli.pipeline, "check_tools", lambda ui_: None)
    monkeypatch.setattr(cli.pipeline, "process", fake_asr(asr))
    assert cli.main(["queue", "add", FEED_URL, "--range", "3", "--yes"]) == 0
    assert cli.main(["queue", "run"]) == 0
    assert calls[-1] == "https://pub.example.org/3.txt" and asr == ["t-html-plain"]
    assert "  ! Herausgeber-Transkript unbrauchbar" in capsys.readouterr().err
    e = q.Queue(tmp_path / "q.json").get(q.key(FEED_URL, "t-html-plain"))
    assert e["status"] == "done" and e["attempts"] == 1
    assert e["backend"] == "faster-whisper"
    assert e["fallback_reason"]


def test_one_falls_back_too(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": b""})
    used = []
    monkeypatch.setattr(cli, "run_one", lambda job, cfg, model: used.append(job.guid))
    assert cli.main(["one", FEED_URL, "t-html-plain", "--yes"]) == 0
    assert used == ["t-html-plain"]
    assert "unbrauchbar" in capsys.readouterr().err


def test_unparseable_never_writes_output(monkeypatch, tmp_path):
    cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": b""})
    monkeypatch.setattr(cli, "run_one", lambda *a: None)
    cli.main(["one", FEED_URL, "t-html-plain", "--yes"])
    assert not list((tmp_path / "out").rglob("*.md")) if (tmp_path / "out").exists() else True


# ---------- queue retry ----------
def failed_queue(tmp_path, n=2):
    state = q.Queue(tmp_path / "q.json")
    for i in range(1, n + 1):
        state.add({**entry(i), "feed_url": FEED_URL})
        k = q.key(FEED_URL, f"g{i}")
        for _ in range(q.MAX_ATTEMPTS):
            state.mark_running(k)
            state.mark_failed(k, "boom")
    state.save()


def test_queue_retry_failed_resets_attempts(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    failed_queue(tmp_path)
    assert cli.main(["queue", "retry", "--failed"]) == 0
    entries = q.Queue(tmp_path / "q.json").entries.values()
    assert {(e["status"], e["attempts"], e.get("force_asr", False)) for e in entries} == {("pending", 0, False)}
    assert "2 Einträge" in capsys.readouterr().err


def test_queue_retry_one_by_index_or_guid_with_asr(monkeypatch, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    failed_queue(tmp_path)
    assert cli.main(["queue", "retry", "2", "--asr"]) == 0
    s = q.Queue(tmp_path / "q.json")
    assert s.get(q.key(FEED_URL, "g2"))["status"] == "pending" and s.get(q.key(FEED_URL, "g2"))["force_asr"]
    assert s.get(q.key(FEED_URL, "g1"))["status"] == "failed"
    assert cli.main(["queue", "retry", "g1"]) == 0
    assert q.Queue(tmp_path / "q.json").get(q.key(FEED_URL, "g1"))["status"] == "pending"


def test_queue_retry_refuses_non_failed_unknown_and_missing_target(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {})
    state = q.Queue(tmp_path / "q.json")
    state.add({**entry(1), "feed_url": FEED_URL})
    state.save()
    assert cli.main(["queue", "retry", "1"]) == 1
    assert "nicht fehlgeschlagen" in capsys.readouterr().err
    assert cli.main(["queue", "retry", "99"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["queue", "retry"])


# ---------- M3: audio_bytes ----------
def test_audio_bytes_in_frontmatter_and_queue(tmp_path):
    from test_pipeline import FakeBackend, fake_fetch, fake_normalise, job, settings
    res = pipeline.process(job(tmp_path), settings(tmp_path), FakeBackend(), ui=ui.Silent(),
                           fetch=fake_fetch(b"12345"), normalise=fake_normalise)
    assert res["audio_bytes"] == 5
    assert markdown.read_frontmatter(res["output"])["audio_bytes"] == 5
    state = q.Queue(tmp_path / "q.json")
    state.add(entry(1))
    state.mark_done(q.key("https://f", "g1"), res)
    assert state.get(q.key("https://f", "g1"))["audio_bytes"] == 5


# ---------- Minors ----------
def test_same_name_files_in_different_folders_do_not_collide(tmp_path):
    a, b = tmp_path / "a" / "talk.mp3", tmp_path / "b" / "talk.mp3"
    for p in (a, b):
        p.parent.mkdir()
        p.write_bytes(b"x")
    out_a = pipeline.output_for(pipeline.file_job(str(a), tmp_path / "out", "en"))
    out_b = pipeline.output_for(pipeline.file_job(str(b), tmp_path / "out", "en"))
    assert out_a != out_b
    assert out_a.name.startswith("talk-") and out_a.parent.name == "files"
    assert out_a == pipeline.output_for(pipeline.file_job(str(a), tmp_path / "out", "en"))  # stable


def test_control_characters_from_feeds_are_stripped(capsys):
    ui.Terminal().result("evil\x1b]52;c;SGVsbG8=\x07title\x9b2J\tok")
    err = capsys.readouterr().err
    assert "\x1b" not in err and "\x07" not in err and "\x9b" not in err
    assert "evil]52;c;SGVsbG8=title2J\tok" in err


@pytest.mark.parametrize("url", ["https://notspotify.com/show/abc", "https://xspotify.com/show/abc"])
def test_lookalike_hosts_are_feeds_not_spotify_or_apple(url):
    assert resolve.classify(url)[0] == "feed"


def test_model_option_ignored_for_publisher_is_said(monkeypatch, capsys, tmp_path):
    cli_env(monkeypatch, tmp_path, {"https://pub.example.org/3.txt": b"Hello.\n"})
    assert cli.main(["one", FEED_URL, "t-html-plain", "--model", "medium", "--yes"]) == 0
    assert "--model medium wird nicht verwendet" in capsys.readouterr().err


def test_corrupt_entry_schema_is_refused(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"version": 1, "entries": {"k": {"status": "weird", "attempts": 0}}}))
    with pytest.raises(q.QueueError, match="k"):
        q.Queue(path)
