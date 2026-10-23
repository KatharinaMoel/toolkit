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
    return fetch(runner, console, root, "opened", images, NOW), err.getvalue()


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
    assert list(tmp_path.iterdir()) == []


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
    assert list(tmp_path.iterdir()) == []


def test_uploads_of_other_projects_are_not_requested(gitlab, tmp_path):
    gitlab.mrs[0]["description"] = f"![x](https://git.example.org/other/proj/uploads/{UPLOAD_ID}/x.png)"
    result, _ = run_fetch(gitlab, tmp_path)
    assert not result.failures
    assert not any("x.png" in c[-1] for c in gitlab.calls)
