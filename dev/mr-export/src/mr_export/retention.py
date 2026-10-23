"""Which snapshot is current (the 'latest' link) and which old ones go.

Only folders named like a fetch made them (<YYYY-MM-DD_HHMM>, optionally -2, -3 ...) are
ever deleted; folders made by hand, without meta.json, are left alone. The newest
complete snapshot is never deleted, whatever followed it."""
import json
import os
import re
import shutil
from pathlib import Path

SNAPSHOT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}_\d{4}(-\d+)?")


def status(path: Path) -> str:
    """'complete', 'partial' (finished with gaps), 'unfinished' (interrupted) or
    'handmade' (no meta.json)."""
    meta = path / "meta.json"
    if not meta.is_file():
        return "handmade"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unfinished"
    # Without the key the folder comes from a version that wrote meta.json only at the
    # end of a successful run - so it is finished.
    if not data.get("complete", True):
        return "unfinished"
    return "partial" if data.get("partial") else "complete"


def _sort_key(path: Path) -> tuple[str, int]:
    """Time stamp first, then the -2, -3 ... of runs in the same minute."""
    m = re.fullmatch(r"(.+?)(?:-(\d+))?", path.name)
    return (m.group(1), int(m.group(2) or 1))


def snapshots(root: Path) -> list[tuple[Path, str]]:
    """Snapshot folders made by fetch, newest first, with their status."""
    if not root.is_dir():
        return []
    found = [p for p in root.iterdir()
             if p.is_dir() and not p.is_symlink() and SNAPSHOT_NAME.fullmatch(p.name)]
    found.sort(key=_sort_key, reverse=True)
    return [(p, status(p)) for p in found]


def current(root: Path) -> Path | None:
    """The newest complete snapshot, or a partial one that is newer than it."""
    return next((p for p, st in snapshots(root) if st in ("complete", "partial")), None)


def update_latest(root: Path) -> Path | None:
    target = current(root)
    if target is None:
        return None
    link, tmp = root / "latest", root / ".latest.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target.name)   # relative, so the folder can be moved as a whole
    os.replace(tmp, link)
    return target


def prune(root: Path, keep: int) -> list[Path]:
    """Keeps the newest `keep` complete snapshots and up to `keep` partial ones newer
    than the newest complete one. Deletes older complete ones, partial ones older than
    the newest complete one, and interrupted ones older than it; returns what went."""
    items = snapshots(root)
    newest_complete = next((p for p, st in items if st == "complete"), None)
    cut = _sort_key(newest_complete) if newest_complete else None
    completes = [p for p, st in items if st == "complete"]
    partials = [p for p, st in items if st == "partial"]
    newer_partials = [p for p in partials if cut is None or _sort_key(p) > cut]
    protected = set(completes[:keep]) | set(newer_partials[:keep]) | {current(root)}
    doomed = [p for p in completes + partials if p not in protected]
    doomed += [p for p, st in items if st == "unfinished" and cut and _sort_key(p) < cut]
    for p in doomed:
        shutil.rmtree(p)
    return doomed
