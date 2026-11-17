import json
from datetime import datetime

import pytest
from conftest import mr

from mr_export import lastrun, snapshot
from mr_export.render import render

NOW = datetime(2026, 10, 23, 12, 0)


def make_snap(root, name, fetched="2026-10-23T11:00:00", **meta):
    p = root / name
    (p / "mr").mkdir(parents=True)
    (p / "mrs.ndjson").write_text(json.dumps(mr(1)) + "\n")
    (p / "meta.json").write_text(json.dumps({"project": "team/app", "fetched_at": fetched, "count": 1,
                                             "complete": True, "partial": False, "failures": [], **meta}))
    return p


def test_write_and_read_round_trip(tmp_path):
    lastrun.write(tmp_path, NOW, "aborted", tmp_path / "2026-10-23_1200", 5, 3, "GitLab does not answer")
    assert lastrun.read(tmp_path) == {"time": "2026-10-23T12:00:00", "status": "aborted",
                                      "snapshot": "2026-10-23_1200", "count": 5, "gaps": 3,
                                      "reason": "GitLab does not answer"}
    with pytest.raises(ValueError):
        lastrun.write(tmp_path, NOW, "fine")


def test_read_ignores_missing_or_broken_files(tmp_path):
    assert lastrun.read(tmp_path) is None
    (tmp_path / "last-run.json").write_text("{not json")
    assert lastrun.read(tmp_path) is None


def test_check_ok_when_complete_and_current(tmp_path):
    make_snap(tmp_path, "2026-10-23_1100")
    lastrun.write(tmp_path, datetime(2026, 10, 23, 11, 0), "complete", tmp_path / "2026-10-23_1100", 1)
    lines, ok = lastrun.check(tmp_path, 3, NOW)
    assert ok and lines[-1].startswith("Verdict:        OK")
    assert any(line.startswith("Latest:         2026-10-23_1100 · complete · 1 MRs") for line in lines)


@pytest.mark.parametrize("status", ["aborted", "unreachable", "partial"])
def test_check_fails_when_the_last_attempt_was_not_complete(tmp_path, status):
    make_snap(tmp_path, "2026-10-23_1100")
    lastrun.write(tmp_path, datetime(2026, 10, 23, 11, 55), status, None, reason="GitLab does not answer")
    lines, ok = lastrun.check(tmp_path, 3, NOW)
    assert not ok
    assert f"Last attempt:   2026-10-23T11:55:00 · {status} · GitLab does not answer" in lines
    assert f"the last attempt was {status}" in lines[-1]


def test_check_fails_when_latest_is_partial_and_lists_gaps(tmp_path):
    make_snap(tmp_path, "2026-10-23_1100", partial=True, failures=["!7: timeout"])
    lines, ok = lastrun.check(tmp_path, 3, NOW)
    assert not ok and "Gaps in latest: 1 - !7: timeout" in lines
    assert "Last attempt:   unknown (no last-run.json yet)" in lines
    assert "Last complete:  none" in lines


def test_check_fails_when_latest_is_stale(tmp_path):
    make_snap(tmp_path, "2026-10-23_0700", fetched="2026-10-23T07:00:00")
    lines, ok = lastrun.check(tmp_path, 3, NOW)
    assert not ok and "older than 3 h" in lines[-1]


def test_check_without_any_snapshot(tmp_path):
    lines, ok = lastrun.check(tmp_path / "nothing", 3, NOW)
    assert not ok and "no snapshot" in lines[-1]


def test_overview_warns_when_a_newer_attempt_failed(tmp_path):
    snap = make_snap(tmp_path, "2026-10-23_1100")
    lastrun.write(tmp_path, datetime(2026, 10, 23, 12, 7), "aborted", tmp_path / "2026-10-23_1207",
                  reason="GitLab does not answer: 3 requests in a row timed out")
    html = render(snapshot.load(snap)).read_text()
    assert "The last attempt (2026-10-23 12:07) stopped before it finished: GitLab does not answer" in html
    assert "Shown here is the snapshot read 2026-10-23 11:00" in html


def test_overview_warns_when_gitlab_was_unreachable(tmp_path):
    snap = make_snap(tmp_path, "2026-10-23_1100")
    lastrun.write(tmp_path, datetime(2026, 10, 23, 12, 7), "unreachable", reason="no answer")
    assert "could not reach GitLab: no answer" in render(snapshot.load(snap)).read_text()


def test_no_warning_when_the_last_attempt_is_this_snapshot(tmp_path):
    snap = make_snap(tmp_path, "2026-10-23_1100")
    lastrun.write(tmp_path, NOW, "complete", snap, 1)
    assert "The last attempt" not in render(snapshot.load(snap)).read_text()


def test_partial_snapshot_says_how_many_mrs_are_incomplete(tmp_path):
    snap = make_snap(tmp_path, "2026-10-23_1100", partial=True, failures=["!1: timeout"], failed_iids=[1])
    html = render(snapshot.load(snap)).read_text()
    assert "Some data could not be read (1 of 1 merge requests incomplete):" in html
