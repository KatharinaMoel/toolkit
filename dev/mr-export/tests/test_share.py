"""A fetch takes uploads from the previous complete snapshot and stores unchanged files
only once (hard links), without ever letting a write in one snapshot change another."""
import json
import os
from datetime import datetime
from io import StringIO

from conftest import UPLOAD_ID

from mr_export import retention, share
from mr_export.fetch import fetch
from mr_export.runner import Console, Runner

FIRST, SECOND = datetime(2026, 10, 23, 10, 5), datetime(2026, 10, 23, 11, 5)


def run_fetch(gitlab, root, now):
    console = Console(StringIO())
    return fetch(Runner(root, console, run=gitlab), console, root, "opened", True, now, {})


def upload_calls(gitlab):
    return [c for c in gitlab.calls if c[0] == "glab" and "uploads/" in c[-1]]


def mark(snap, **meta):
    data = json.loads((snap / "meta.json").read_text())
    data.update(meta)
    (snap / "meta.json").write_text(json.dumps(data))


def test_uploads_of_the_previous_complete_snapshot_are_not_downloaded_again(gitlab, tmp_path):
    first = run_fetch(gitlab, tmp_path, FIRST)
    gitlab.calls.clear()
    second = run_fetch(gitlab, tmp_path, SECOND)
    assert upload_calls(gitlab) == []
    assert second.images == 2 and second.images_reused == 2 and not second.failures
    for name in ("a.png", "screen one.png"):
        old, new = first.path / "uploads" / UPLOAD_ID / name, second.path / "uploads" / UPLOAD_ID / name
        assert os.path.samefile(old, new)


def test_a_new_upload_is_still_downloaded(gitlab, tmp_path):
    run_fetch(gitlab, tmp_path, FIRST)
    gitlab.mrs[0]["description"] = f"![n](/uploads/{UPLOAD_ID}/new.png)"
    gitlab.uploads[f"{UPLOAD_ID}/new.png"] = b"PNG-NEW"
    gitlab.calls.clear()
    second = run_fetch(gitlab, tmp_path, SECOND)
    assert [c[-1].rsplit("/", 1)[1] for c in upload_calls(gitlab)] == ["new.png"]
    assert (second.path / "uploads" / UPLOAD_ID / "new.png").read_bytes() == b"PNG-NEW"
    assert second.images == 3 and second.images_reused == 2


def test_uploads_are_not_taken_from_an_unfinished_or_partial_run(gitlab, tmp_path):
    for status in ({"complete": False}, {"partial": True}):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        first = run_fetch(gitlab, root, FIRST)
        mark(first.path, **status)
        gitlab.calls.clear()
        second = run_fetch(gitlab, root, SECOND)
        assert len(upload_calls(gitlab)) == 2, status
        assert second.images_reused == 0
        assert not os.path.samefile(first.path / "uploads" / UPLOAD_ID / "a.png",
                                    second.path / "uploads" / UPLOAD_ID / "a.png")


def test_an_empty_upload_in_the_previous_snapshot_is_downloaded_again(gitlab, tmp_path):
    first = run_fetch(gitlab, tmp_path, FIRST)
    (first.path / "uploads" / UPLOAD_ID / "a.png").write_bytes(b"")
    gitlab.calls.clear()
    second = run_fetch(gitlab, tmp_path, SECOND)
    assert [c[-1].rsplit("/", 1)[1] for c in upload_calls(gitlab)] == ["a.png"]
    assert (second.path / "uploads" / UPLOAD_ID / "a.png").read_bytes() == b"PNG-A"


def test_without_hard_links_the_upload_is_copied_not_downloaded(gitlab, tmp_path, monkeypatch):
    run_fetch(gitlab, tmp_path, FIRST)

    def no_links(*a, **k):
        raise OSError("hard links not supported")
    monkeypatch.setattr(os, "link", no_links)
    gitlab.calls.clear()
    second = run_fetch(gitlab, tmp_path, SECOND)
    assert upload_calls(gitlab) == [] and not second.failures
    assert (second.path / "uploads" / UPLOAD_ID / "a.png").read_bytes() == b"PNG-A"
    assert second.shared_files == 0   # sharing is best effort and just skipped


def test_unchanged_files_are_stored_once_and_changed_ones_stay_apart(gitlab, tmp_path):
    first = run_fetch(gitlab, tmp_path, FIRST)
    gitlab.mrs[1]["title"] = "FIX: renamed"
    second = run_fetch(gitlab, tmp_path, SECOND)
    same = lambda rel: os.path.samefile(first.path / rel, second.path / rel)
    assert same("mr/1.json") and same("mr/1-approvals.json") and same("mr/2-discussions.ndjson")
    assert not same("mr/2.json") and not same("mrs.ndjson")
    assert json.loads((second.path / "mr" / "2.json").read_text())["title"] == "FIX: renamed"
    assert second.shared_files > 0 and second.shared_bytes > 0


def test_pages_and_meta_are_never_shared(tmp_path):
    prev, snap = tmp_path / "prev", tmp_path / "snap"
    for d in (prev, snap):
        (d / "mr").mkdir(parents=True)
        for rel in ("index.html", "mr/1.html", "meta.json", "mr/1.json"):
            (d / rel).write_text("same bytes")
    shared = share.share_unchanged(snap, prev)
    assert shared.files == 1 and os.path.samefile(prev / "mr/1.json", snap / "mr/1.json")
    for rel in ("index.html", "mr/1.html", "meta.json"):
        assert not os.path.samefile(prev / rel, snap / rel), rel


def test_deleting_the_old_snapshot_keeps_the_shared_files(gitlab, tmp_path):
    run_fetch(gitlab, tmp_path, FIRST)
    second = run_fetch(gitlab, tmp_path, SECOND)
    data = (second.path / "mr" / "1.json").read_bytes()
    gone = retention.prune(tmp_path, keep=1)
    assert [p.name for p in gone] == ["2026-10-23_1005"]
    assert (second.path / "mr" / "1.json").read_bytes() == data
    assert (second.path / "uploads" / UPLOAD_ID / "a.png").read_bytes() == b"PNG-A"


def test_symlinks_in_the_previous_snapshot_are_not_followed(tmp_path):
    prev, snap = tmp_path / "prev", tmp_path / "snap"
    prev.mkdir(), snap.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("x")
    (prev / "a.json").symlink_to(outside)
    (snap / "a.json").write_text("x")
    assert share.share_unchanged(snap, prev).files == 0
    assert not os.path.samefile(outside, snap / "a.json")


def test_first_run_has_nothing_to_share(gitlab, tmp_path):
    result = run_fetch(gitlab, tmp_path, FIRST)
    assert result.shared_files == 0 and result.images_reused == 0 and len(upload_calls(gitlab)) == 2
