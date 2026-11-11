"""Snapshots share what has not changed with the snapshot before them.

Each snapshot stays a full folder of its own, but a file whose bytes are the same as in
the previous complete snapshot becomes a hard link to it: it is stored once, and deleting
the older folder leaves the newer one intact. Only files that nothing writes again are
shared - the pages (*.html, rewritten by `render`) and meta.json (rewritten during a run)
always stay separate files, so writing one of them can never change another snapshot."""
import filecmp
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import retention

NEVER_SHARED_NAMES = {"meta.json"}
NEVER_SHARED_SUFFIXES = {".html"}


@dataclass
class Shared:
    files: int = 0
    bytes: int = 0


def previous_complete(root: Path) -> Path | None:
    """The newest complete snapshot under root: its files were all written to the end.
    Unfinished runs may hold half-written files, and partial ones are not trusted either."""
    return next((p for p, st in retention.snapshots(root) if st == "complete"), None)


def shareable(rel: Path) -> bool:
    return rel.name not in NEVER_SHARED_NAMES and rel.suffix not in NEVER_SHARED_SUFFIXES


def existing_file(path: Path) -> bool:
    """A regular, non-empty file - not a link that could point anywhere."""
    return not path.is_symlink() and path.is_file() and path.stat().st_size > 0


def link_or_copy(src: Path, dst: Path) -> None:
    """A hard link where the file system allows it, a copy otherwise (other device,
    too many links); either way without asking GitLab again."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def share_unchanged(snap: Path, previous: Path | None) -> Shared:
    """Replaces each shareable file in snap that has the same bytes as the same path in
    previous by a hard link to that file. Best effort: a file that cannot be linked stays
    as it is, the snapshot is complete either way."""
    shared = Shared()
    if previous is None or previous.resolve() == snap.resolve():
        return shared
    for path in sorted(snap.rglob("*")):
        rel = path.relative_to(snap)
        if path.is_symlink() or not path.is_file() or not shareable(rel):
            continue
        old = previous / rel
        try:
            if (not existing_file(old) or os.path.samefile(old, path)
                    or old.stat().st_size != path.stat().st_size
                    or not filecmp.cmp(old, path, shallow=False)):
                continue
            tmp = path.with_name(f".{path.name}.share")
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
            os.link(old, tmp)
            try:
                os.replace(tmp, path)   # atomic: path is either the old file or the link
            except OSError:
                tmp.unlink()
                raise
        except OSError:
            continue
        shared.files += 1
        shared.bytes += path.stat().st_size
    return shared
