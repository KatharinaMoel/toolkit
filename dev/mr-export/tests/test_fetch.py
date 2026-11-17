import json
from datetime import datetime
from io import StringIO

import pytest
from conftest import UPLOAD_ID

from mr_export.fetch import fetch, new_snapshot_dir
from mr_export.runner import FORBIDDEN_GLAB_ARGS, Console, Runner

NOW = datetime(2026, 10, 23, 10, 5)


def run_fetch(gitlab, root, images=True):
    err = StringIO()
    console = Console(err)
    runner = Runner(root, console, run=gitlab)
    return fetch(runner, console, root, "opened", images, NOW,
                 {"dev": "notfall/dev", "main": "notfall/main"}), err.getvalue()


def test_writes_the_snapshot_layout(gitlab, tmp_path):
    result, _ = run_fetch(gitlab, tmp_path)
    snap = tmp_path / "2026-10-23_1005"
    assert result.path == snap and result.count == 2 and not result.failures
    for name in ("meta.json", "mrs.ndjson", "mr/1.json", "mr/2-discussions.ndjson", "mr/1-approvals.json"):
        assert (snap / name).is_file(), name
    meta = json.loads((snap / "meta.json").read_text())
    assert meta["project"] == "team/app" and meta["state"] == "opened"


def test_only_get_requests_reach_glab(gitlab, tmp_path):
    run_fetch(gitlab, tmp_path)
    glab = [c for c in gitlab.calls if c[0] == "glab"]
    assert glab and all(c[:2] == ["glab", "api"] for c in glab)
    assert not any(a in FORBIDDEN_GLAB_ARGS for c in glab for a in c)


def test_runner_refuses_arguments_that_could_write(tmp_path):
    runner = Runner(tmp_path, Console(StringIO()), run=lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(ValueError):
        runner.glab_get("projects/:id --method DELETE", "x")
    with pytest.raises(ValueError):
        runner.glab_get("users", "x")


def test_images_are_saved_under_their_plain_name(gitlab, tmp_path):
    result, _ = run_fetch(gitlab, tmp_path)
    up = result.path / "uploads" / UPLOAD_ID
    assert (up / "a.png").read_bytes() == b"PNG-A"
    assert (up / "screen one.png").read_bytes() == b"PNG-B"   # %20 in the link, space on disk
    assert result.images == 2


def test_no_images_when_switched_off(gitlab, tmp_path):
    result, _ = run_fetch(gitlab, tmp_path, images=False)
    assert not (result.path / "uploads").exists()
    assert not any("uploads" in c[-1] for c in gitlab.calls)


def test_never_writes_into_an_existing_snapshot(gitlab, tmp_path):
    first, _ = run_fetch(gitlab, tmp_path)
    second, _ = run_fetch(gitlab, tmp_path)
    assert first.path.name == "2026-10-23_1005" and second.path.name == "2026-10-23_1005-2"
    assert new_snapshot_dir(tmp_path, NOW).name == "2026-10-23_1005-3"


def test_a_failing_mr_is_reported_and_the_rest_continues(gitlab, tmp_path):
    gitlab.fail.add("projects/:id/merge_requests/2/approvals")
    result, err = run_fetch(gitlab, tmp_path)
    assert result.failures and "!2" in result.failures[0]
    assert (result.path / "mr" / "1.json").is_file()
    assert "!2" in json.loads((result.path / "meta.json").read_text())["failures"][0]
    assert "! !2 failed" in err


def test_no_folder_when_the_list_cannot_be_read(gitlab, tmp_path):
    gitlab.fail.add("projects/:id/merge_requests?state=opened&per_page=100")
    with pytest.raises(Exception):
        run_fetch(gitlab, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".fetch.lock", "last-run.json"]   # no snapshot folder
    assert json.loads((tmp_path / "last-run.json").read_text())["status"] == "unreachable"


def test_explains_each_call_once_with_the_command(gitlab, tmp_path):
    _, err = run_fetch(gitlab, tmp_path)
    assert "* Read !1 in full" in err and "  > glab api projects/:id/merge_requests/1" in err
    assert "* Read !2 in full" not in err          # repeats run as one result line each
    assert "  = !2: 2 threads, 2 notes" in err


def test_read_only_guard_refuses_each_write_flag():
    from mr_export.runner import assert_read_only
    for flag in FORBIDDEN_GLAB_ARGS:
        with pytest.raises(ValueError):
            assert_read_only(["glab", "api", flag, "x", "projects/:id"])
    assert_read_only(["glab", "api", "--paginate", "--output", "ndjson", "projects/:id"])


def test_every_glab_call_passes_the_guard(gitlab, tmp_path, monkeypatch):
    import mr_export.runner as runner_mod
    seen = []
    monkeypatch.setattr(runner_mod, "assert_read_only", lambda args: seen.append(list(args)))
    run_fetch(gitlab, tmp_path)
    assert seen == [c for c in gitlab.calls if c[0] == "glab"]


def test_interrupted_read_is_marked_unfinished(gitlab, tmp_path):
    def boom(*a, **k):
        raise KeyboardInterrupt
    gitlab.answer_orig = gitlab.answer
    gitlab.answer = lambda cmd: boom() if cmd[-1].endswith("/2") else gitlab.answer_orig(cmd)
    with pytest.raises(KeyboardInterrupt):
        run_fetch(gitlab, tmp_path)
    snap = tmp_path / "2026-10-23_1005"
    assert json.loads((snap / "meta.json").read_text())["complete"] is False


def test_bad_list_answer_leaves_no_folder(gitlab, tmp_path):
    gitlab.answer_orig = gitlab.answer
    gitlab.answer = lambda cmd: "not json\n" if "merge_requests?" in cmd[-1] else gitlab.answer_orig(cmd)
    with pytest.raises(json.JSONDecodeError):
        run_fetch(gitlab, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".fetch.lock", "last-run.json"]   # no snapshot folder
    assert json.loads((tmp_path / "last-run.json").read_text())["status"] == "unreachable"


def test_uploads_of_other_projects_are_not_requested(gitlab, tmp_path):
    gitlab.mrs[0]["description"] = f"![x](https://git.example.org/other/proj/uploads/{UPLOAD_ID}/x.png)"
    result, _ = run_fetch(gitlab, tmp_path)
    assert not result.failures
    assert not any("x.png" in c[-1] for c in gitlab.calls)


def test_bad_mr_number_is_a_failure_and_writes_nothing(gitlab, tmp_path):
    gitlab.mrs[0]["iid"] = "../evil"
    result, _ = run_fetch(gitlab, tmp_path)
    assert any("../evil" in f for f in result.failures)
    assert not any("evil" in c[-1] for c in gitlab.calls)
    assert not list(tmp_path.rglob("*evil*"))


def test_members_are_saved(gitlab, tmp_path):
    result, _ = run_fetch(gitlab, tmp_path)
    lines = (result.path / "members.ndjson").read_text().splitlines()
    assert [json.loads(x)["username"] for x in lines] == ["alice", "bob"]


def test_git_state_collector_gets_mrs_and_emergency_branches(gitlab, tmp_path, no_git_state):
    result, _ = run_fetch(gitlab, tmp_path)
    assert no_git_state[0]["mrs"] == [1, 2]
    assert no_git_state[0]["emergency"] == {"dev": "notfall/dev", "main": "notfall/main"}
    assert json.loads((result.path / "meta.json").read_text())["partial"] is False


def test_git_failure_makes_run_partial(gitlab, tmp_path, monkeypatch):
    import mr_export.fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "collect_git_state", lambda *a: ["git: ssh: connect timed out"])
    result, _ = run_fetch(gitlab, tmp_path)
    meta = json.loads((result.path / "meta.json").read_text())
    assert meta["partial"] is True and meta["complete"] is True
    assert "git: ssh: connect timed out" in meta["failures"]


def test_second_fetch_waits_for_lock_and_stops(gitlab, tmp_path):
    import fcntl
    from mr_export.fetch import FetchLocked
    with open(tmp_path / ".fetch.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(FetchLocked):
            run_fetch(gitlab, tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [".fetch.lock"]
    assert not any(c[0] == "glab" for c in gitlab.calls)


def test_quiet_console_prints_only_notes():
    buf = StringIO()
    c = Console(buf, quiet=True)
    c.step("explain", ["git", "x"])
    c.result("ok")
    c.line("header")
    c.note("problem")
    assert buf.getvalue().strip() == "! problem"


def mrs_of(gitlab, n):
    from conftest import mr
    gitlab.mrs[:] = [mr(i) for i in range(1, n + 1)]


def test_three_timeouts_in_a_row_stop_the_run(gitlab, tmp_path):
    from mr_export.fetch import FetchAborted
    mrs_of(gitlab, 6)
    gitlab.hang = lambda ep: ep.startswith("projects/:id/merge_requests/") and not ep.startswith(
        "projects/:id/merge_requests/1")
    with pytest.raises(FetchAborted, match="GitLab does not answer"):
        run_fetch(gitlab, tmp_path)
    snap = tmp_path / "2026-10-23_1005"
    meta = json.loads((snap / "meta.json").read_text())
    assert meta["complete"] is False and "does not answer" in meta["aborted"]
    assert meta["failed_iids"] == [2, 3, 4]
    asked = [c[-1] for c in gitlab.calls if c[0] == "glab"]
    assert not any("merge_requests/5" in ep for ep in asked)   # stopped after the third
    assert not any("members" in ep for ep in asked)


def test_timeouts_with_answers_in_between_do_not_stop(gitlab, tmp_path):
    mrs_of(gitlab, 6)
    gitlab.hang = lambda ep: ep in ("projects/:id/merge_requests/1", "projects/:id/merge_requests/2",
                                    "projects/:id/merge_requests/4", "projects/:id/merge_requests/5")
    result, _ = run_fetch(gitlab, tmp_path)
    assert len(result.failures) == 4
    assert json.loads((result.path / "meta.json").read_text())["complete"] is True


def test_other_errors_reset_the_timeout_count(gitlab, tmp_path):
    mrs_of(gitlab, 5)
    gitlab.hang = lambda ep: ep in ("projects/:id/merge_requests/1", "projects/:id/merge_requests/2",
                                    "projects/:id/merge_requests/4", "projects/:id/merge_requests/5")
    gitlab.fail.add("projects/:id/merge_requests/3")
    result, _ = run_fetch(gitlab, tmp_path)
    assert len(result.failures) == 5


def test_hanging_upload_downloads_stop_the_run(gitlab, tmp_path):
    from mr_export.fetch import FetchAborted
    gitlab.mrs[:] = [gitlab.mrs[1]]
    gitlab.mrs[0]["description"] = " ".join(f"![{i}](/uploads/{UPLOAD_ID}/{i}.png)" for i in range(5))
    gitlab.hang = lambda ep: ep.startswith("projects/:id/uploads/")
    with pytest.raises(FetchAborted):
        run_fetch(gitlab, tmp_path)
    assert sum(1 for c in gitlab.calls if "uploads/" in c[-1]) == 3


def test_runner_reports_a_timeout_as_its_own_error(tmp_path):
    import subprocess
    from mr_export.runner import CommandError, CommandTimeout

    def silent(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    with pytest.raises(CommandTimeout, match="no answer within"):
        Runner(tmp_path, Console(StringIO()), run=silent).glab_get("projects/:id", None)
    assert issubclass(CommandTimeout, CommandError)


def last_run(root):
    return json.loads((root / "last-run.json").read_text())


def test_last_run_complete(gitlab, tmp_path):
    result, _ = run_fetch(gitlab, tmp_path)
    assert last_run(tmp_path) == {"time": "2026-10-23T10:05:00", "status": "complete",
                                  "snapshot": result.path.name, "count": 2, "gaps": 0, "reason": None}


def test_last_run_partial(gitlab, tmp_path):
    gitlab.fail.add("projects/:id/merge_requests/2/approvals")
    run_fetch(gitlab, tmp_path)
    lr = last_run(tmp_path)
    assert lr["status"] == "partial" and lr["gaps"] == 1 and lr["count"] == 2


def test_last_run_aborted_after_timeouts(gitlab, tmp_path):
    from mr_export.fetch import FetchAborted
    mrs_of(gitlab, 4)
    gitlab.hang = lambda ep: ep.startswith("projects/:id/merge_requests/")
    with pytest.raises(FetchAborted):
        run_fetch(gitlab, tmp_path)
    lr = last_run(tmp_path)
    assert lr["status"] == "aborted" and lr["snapshot"] == "2026-10-23_1005" and lr["gaps"] == 3
    assert "does not answer" in lr["reason"]


def test_last_run_unreachable_when_gitlab_times_out_at_once(gitlab, tmp_path):
    gitlab.hang = lambda ep: True
    with pytest.raises(Exception):
        run_fetch(gitlab, tmp_path)
    lr = last_run(tmp_path)
    assert lr["status"] == "unreachable" and lr["snapshot"] is None and "no answer within" in lr["reason"]


def test_last_run_aborted_when_interrupted(gitlab, tmp_path):
    gitlab.answer_orig = gitlab.answer

    def answer(cmd):
        if cmd[-1].endswith("/2"):
            raise KeyboardInterrupt
        return gitlab.answer_orig(cmd)
    gitlab.answer = answer
    with pytest.raises(KeyboardInterrupt):
        run_fetch(gitlab, tmp_path)
    assert last_run(tmp_path)["status"] == "aborted" and last_run(tmp_path)["reason"] == "interrupted"


def test_labels_are_saved_with_their_priority(gitlab, tmp_path):
    result, err = run_fetch(gitlab, tmp_path)
    assert json.loads((result.path / "labels.json").read_text()) == [
        {"name": "Small", "priority": None}, {"name": "Ready", "priority": 1}]
    assert "2 labels, 1 with a priority" in err


def test_failing_labels_do_not_break_the_run(gitlab, tmp_path):
    gitlab.fail.add("projects/:id/labels?per_page=100")
    result, err = run_fetch(gitlab, tmp_path)
    assert not result.failures and not (result.path / "labels.json").exists()
    assert "labels could not be read" in err
    assert last_run(tmp_path)["status"] == "complete"
