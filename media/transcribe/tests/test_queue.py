import json
import os

import pytest

from transcribe import markdown
from transcribe import queue as q

FEED = "https://feeds.example.org/show"


def entry(i, **extra):
    return {"feed_url": FEED, "guid": f"g{i}", "index": i, "title": f"Episode {i}", **extra}


def fake_worker(tmp_path, calls, sha="aa" * 32, fail=()):
    """Stands in for download+transcribe: writes an output with the given audio sha."""
    def work(e):
        calls.append(e["guid"])
        if e["guid"] in fail:
            raise RuntimeError("boom")
        out = tmp_path / "out" / f"{e['index']:03d}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f'---\naudio_sha256: "{sha}"\n---\n\ntext\n')
        return {"output": str(out), "audio_sha256": sha, "audio_seconds": 600.0, "compute_seconds": 66.0}
    return work


def test_add_creates_pending_and_is_idempotent(tmp_path):
    state = q.Queue(tmp_path / "q.json")
    assert state.add(entry(1)) is True
    assert state.add(entry(1)) is False
    state.save()
    data = json.loads((tmp_path / "q.json").read_text())
    (e,) = data["entries"].values()
    assert e["status"] == "pending" and e["attempts"] == 0


def test_add_does_not_reset_done(tmp_path):
    state = q.Queue(tmp_path / "q.json")
    state.add(entry(1))
    state.mark_done(q.key(FEED, "g1"), {"output": "x", "audio_sha256": "s"})
    assert state.add(entry(1)) is False
    assert state.get(q.key(FEED, "g1"))["status"] == "done"


def test_run_moves_pending_to_running_to_done(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    seen = []

    def work(e):
        # while working, the state on disk says running
        on_disk = json.loads(path.read_text())["entries"][q.key(FEED, "g1")]
        seen.append(on_disk["status"])
        return fake_worker(tmp_path, [])(e)

    report = q.run(path, work)
    assert seen == ["running"]
    e = q.Queue(path).get(q.key(FEED, "g1"))
    assert e["status"] == "done" and e["error"] is None
    assert e["timings"]["compute_seconds"] == 66.0
    assert [r["status"] for r in report] == ["done"]


def test_failure_is_recorded_and_others_continue(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    for i in (1, 2):
        state.add(entry(i))
    state.save()
    calls = []
    report = q.run(path, fake_worker(tmp_path, calls, fail={"g1"}))
    assert calls == ["g1", "g2"]
    s = q.Queue(path)
    assert s.get(q.key(FEED, "g1"))["status"] == "failed"
    assert "boom" in s.get(q.key(FEED, "g1"))["error"]
    assert s.get(q.key(FEED, "g2"))["status"] == "done"
    assert [r["status"] for r in report] == ["failed", "done"]


def test_failed_is_retried_until_max_attempts(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    calls = []
    for _ in range(q.MAX_ATTEMPTS + 2):
        q.run(path, fake_worker(tmp_path, calls, fail={"g1"}))
    assert len(calls) == q.MAX_ATTEMPTS


def test_crash_recovery_running_becomes_pending(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.mark_running(q.key(FEED, "g1"))
    state.save()  # process "killed" here
    calls = []
    q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1"]
    assert q.Queue(path).get(q.key(FEED, "g1"))["status"] == "done"


def test_second_run_does_no_work(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    for i in (1, 2):
        state.add(entry(i))
    state.save()
    calls = []
    q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1", "g2"]
    before = path.read_text()
    report = q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1", "g2"] and report == []
    assert path.read_text() == before


def test_done_with_missing_output_is_redone(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    calls = []
    q.run(path, fake_worker(tmp_path, calls))
    os.remove(q.Queue(path).get(q.key(FEED, "g1"))["output"])
    q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1", "g1"]


def test_sha_mismatch_is_redone(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    calls = []
    q.run(path, fake_worker(tmp_path, calls, sha="aa" * 32))
    out = q.Queue(path).get(q.key(FEED, "g1"))["output"]
    with open(out, "w") as f:  # output now belongs to other audio
        f.write('---\naudio_sha256: "' + "bb" * 32 + '"\n---\n')
    q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1", "g1"]
    assert markdown.read_frontmatter(out)["audio_sha256"] == "aa" * 32


def test_max_limits_work(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    for i in (1, 2, 3):
        state.add(entry(i))
    state.save()
    calls = []
    q.run(path, fake_worker(tmp_path, calls), max_items=2)
    assert calls == ["g1", "g2"]


def test_order_follows_feed_then_index(tmp_path):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    for i in (3, 1, 2):
        state.add(entry(i))
    state.save()
    calls = []
    q.run(path, fake_worker(tmp_path, calls))
    assert calls == ["g1", "g2", "g3"]


def test_save_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "q.json"
    state = q.Queue(path)
    state.add(entry(1))
    state.save()
    good = path.read_text()
    state.add(entry(2))

    def broken_replace(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(q.os, "replace", broken_replace)
    with pytest.raises(OSError):
        state.save()
    assert path.read_text() == good
    assert [p.name for p in tmp_path.iterdir()] == ["q.json"]


def test_concurrent_run_is_refused(tmp_path):
    path = tmp_path / "q.json"
    q.Queue(path).save()
    with q.locked(path):
        with pytest.raises(q.QueueError, match="gesperrt"):
            with q.locked(path):
                pass


def test_corrupt_state_is_refused_not_overwritten(tmp_path):
    path = tmp_path / "q.json"
    path.write_text("{not json")
    with pytest.raises(q.QueueError):
        q.Queue(path)
    assert path.read_text() == "{not json"


def test_counter_proof_sha_check_is_load_bearing(tmp_path, monkeypatch):
    """Without the output check a done entry with foreign output would be skipped."""
    monkeypatch.setattr(q, "output_is_valid", lambda e: True)
    with pytest.raises(AssertionError):
        test_sha_mismatch_is_redone(tmp_path)
