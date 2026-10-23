import json
import os

from mr_export import retention


def snap(root, name, status="complete"):
    p = root / name
    (p / "mr").mkdir(parents=True)
    (p / "mrs.ndjson").write_text("")
    if status != "handmade":
        meta = {"complete": status != "unfinished", "partial": status == "partial"}
        (p / "meta.json").write_text(json.dumps(meta))
    return p


def name(i, minute=0):
    return f"2026-10-{i:02d}_10{minute:02d}"


def test_status_values(tmp_path):
    assert retention.status(snap(tmp_path, name(1), "complete")) == "complete"
    assert retention.status(snap(tmp_path, name(2), "partial")) == "partial"
    assert retention.status(snap(tmp_path, name(3), "unfinished")) == "unfinished"
    assert retention.status(snap(tmp_path, "by-hand", "handmade")) == "handmade"


def test_latest_points_to_newest_complete(tmp_path):
    snap(tmp_path, name(1))
    newest = snap(tmp_path, name(2))
    assert retention.update_latest(tmp_path) == newest
    link = tmp_path / "latest"
    assert link.is_symlink() and os.readlink(link) == newest.name   # relative target
    assert (link / "mrs.ndjson").exists()


def test_latest_prefers_complete_over_older_partial(tmp_path):
    snap(tmp_path, name(1), "partial")
    complete = snap(tmp_path, name(2))
    assert retention.update_latest(tmp_path) == complete


def test_latest_takes_newer_partial(tmp_path):
    snap(tmp_path, name(1))
    partial = snap(tmp_path, name(2), "partial")
    assert retention.update_latest(tmp_path) == partial


def test_unfinished_never_becomes_latest(tmp_path):
    complete = snap(tmp_path, name(1))
    snap(tmp_path, name(2), "unfinished")
    assert retention.update_latest(tmp_path) == complete


def test_latest_is_replaced_not_followed(tmp_path):
    first = snap(tmp_path, name(1))
    retention.update_latest(tmp_path)
    second = snap(tmp_path, name(2))
    retention.update_latest(tmp_path)
    assert os.readlink(tmp_path / "latest") == second.name and first.exists()


def test_prune_keeps_newest_n(tmp_path):
    for i in range(1, 21):
        snap(tmp_path, name(i))
    deleted = retention.prune(tmp_path, 15)
    assert sorted(p.name for p in deleted) == [name(i) for i in range(1, 6)]
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 15


def test_prune_never_deletes_newest_complete(tmp_path):
    complete = snap(tmp_path, name(1))
    for i in range(2, 18):
        snap(tmp_path, name(i), "partial")
    retention.prune(tmp_path, 15)
    assert complete.exists()


def test_prune_drops_old_unfinished_keeps_newest_unfinished(tmp_path):
    old = snap(tmp_path, name(1), "unfinished")
    snap(tmp_path, name(2))
    newest = snap(tmp_path, name(3), "unfinished")
    retention.prune(tmp_path, 15)
    assert not old.exists() and newest.exists()


def test_prune_ignores_foreign_folders(tmp_path):
    for i in range(1, 18):
        snap(tmp_path, name(i))
    retention.update_latest(tmp_path)
    foreign = [snap(tmp_path, "2026-10-23_1005-notfall"), tmp_path / "notes"]
    foreign[1].mkdir()
    handmade = snap(tmp_path, name(0, 1), "handmade")
    retention.prune(tmp_path, 15)
    assert all(p.exists() for p in foreign) and handmade.exists()
    assert (tmp_path / "latest").is_symlink()


def test_snapshot_from_first_version_counts_as_complete(tmp_path):
    """The first version wrote meta.json only at the end and without 'complete'."""
    old = tmp_path / name(1)
    (old / "mr").mkdir(parents=True)
    (old / "mrs.ndjson").write_text("")
    (old / "meta.json").write_text(json.dumps({"project": "team/app", "fetched_at": "2026-10-01T10:00:00"}))
    snap(tmp_path, name(2))
    assert retention.status(old) == "complete"
    retention.prune(tmp_path, 15)
    assert old.exists()


def test_keep_counts_complete_snapshots_only(tmp_path):
    completes = [snap(tmp_path, name(i)) for i in (1, 2, 3)]
    for i in range(4, 19):
        snap(tmp_path, name(i), "partial")
    retention.prune(tmp_path, 15)
    assert all(p.exists() for p in completes)


def test_partial_runs_are_capped_too(tmp_path):
    snap(tmp_path, name(1))
    partials = [snap(tmp_path, name(i), "partial") for i in range(2, 22)]   # 20 newer partial runs
    retention.prune(tmp_path, 15)
    assert [p.exists() for p in partials].count(True) == 15
    assert all(p.exists() for p in partials[-15:])
