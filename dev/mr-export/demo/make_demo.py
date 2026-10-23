"""Writes an invented snapshot (a garden planning app, people alice/bob/carol/dan) and
renders it - for screenshots in the README and as a quick look at the pages.

    python3 dev/mr-export/demo/make_demo.py <out_dir> [--screenshots <img_dir>]

With --screenshots, headless Firefox captures overview.png and mr-page.png."""
import argparse
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mr_export import snapshot  # noqa: E402
from mr_export.render import render  # noqa: E402

WEB = "https://gitlab.example.org/acme/garden-planner"
UPLOAD = "5f0c3a9e1d2b4c6a8e0f1a2b3c4d5e6f"


def png(width: int, height: int) -> bytes:
    """A small striped PNG, built by hand so the demo needs no image library."""
    rows = b"".join(b"\x00" + b"".join(
        bytes((120, 170, 110) if (x // 24 + y // 24) % 2 else (210, 225, 200)) for x in range(width))
        for y in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def person(name):
    return {"username": name}


def mr(iid, title, author, labels, draft=False, pipeline="success", hours_ago=2, desc="", reviewers=()):
    updated = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"iid": iid, "title": ("Draft: " if draft else "") + title, "draft": draft, "state": "opened",
            "source_branch": f"feat/{iid}-{title.split()[0].lower()}", "target_branch": "dev",
            "author": person(author), "assignees": [], "reviewers": [person(r) for r in reviewers],
            "labels": labels, "head_pipeline": {"status": pipeline}, "web_url": f"{WEB}/-/merge_requests/{iid}",
            "created_at": updated, "updated_at": updated, "description": desc, "sha": f"{iid:040x}",
            "detailed_merge_status": "draft_status" if draft else "not_approved"}


def diff(path, added, removed=0):
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}",
             f"@@ -1,{removed} +1,{added} @@"]
    lines += [f"-old line {i}" for i in range(removed)] + [f"+new line {i}" for i in range(added)]
    return "\n".join(lines) + "\n"


MRS = [
    (mr(106, "Seed calendar shows frost dates per region", "dan", ["Release"], reviewers=["alice"],
        desc="Adds frost dates from the regional table.\n\n## How to test\n1. Open **Calendar**\n2. Pick a region"),
     {"target": "no", "emergency": "yes", "emergency_branch": "notfall/dev"}, diff("calendar/frost.py", 14, 3)),
    (mr(101, "Watering reminders respect rain forecast", "alice", ["Approval ready", "Urgent"],
        reviewers=["bob"], hours_ago=1,
        desc="Skips a reminder when more than 5 mm of rain are forecast.\n\n```python\nif rain_mm > 5:\n    skip()\n```"),
     {"target": "no", "emergency": None, "emergency_branch": None},
     diff("reminders/watering.py", 6, 2) + diff("reminders/tests/test_watering.py", 9)),
    (mr(104, "Plant list export as CSV", "bob", ["Approval ready"], hours_ago=5, reviewers=["carol"]),
     {"target": "content", "emergency": None, "emergency_branch": None}, diff("export/csv.py", 21)),
    (mr(102, "Bed planner: drag plants between beds", "carol", ["Docs"], pipeline="running",
        reviewers=["alice", "dan"], hours_ago=3,
        desc=f"Plants can now be moved between beds.\n\n![Bed planner](/uploads/{UPLOAD}/bed-planner.png)"),
     {"target": "no", "emergency": None, "emergency_branch": None},
     diff("planner/static/drag.js", 8, 4) + diff("docs/planner.md", 5)),
    (mr(103, "Harvest log keeps photos", "dan", ["Urgent"], draft=True, pipeline="failed", hours_ago=7),
     {"target": "no", "emergency": None, "emergency_branch": None}, diff("harvest/photos.py", 4)),
    (mr(105, "Rewrite the soil database import", "alice", [], draft=True, hours_ago=26),
     {"target": "unknown", "emergency": None, "emergency_branch": None}, diff("soil/import.py", 1800, 900)),
]

THREADS = {
    102: [{"notes": [{"body": "Dropping onto a full bed loses the plant - can we refuse the drop?",
                      "author": person("alice"), "created_at": "2026-01-14T10:02:00Z", "system": False,
                      "resolvable": True, "resolved": False,
                      "position": {"new_path": "planner/static/drag.js", "new_line": 42}},
                     {"body": "Good catch, I will show a message instead.", "author": person("carol"),
                      "created_at": "2026-01-14T10:20:00Z", "system": False}]},
          {"notes": [{"body": "requested review from @dan", "author": person("carol"),
                      "created_at": "2026-01-14T09:00:00Z", "system": True}]}],
    101: [{"notes": [{"body": "Looks good to me.", "author": person("bob"), "created_at": "2026-01-14T11:00:00Z",
                      "system": False, "resolvable": True, "resolved": True}]}],
}

APPROVALS = {101: ["bob"], 104: ["carol"], 106: ["alice"]}


def write_demo(out: Path) -> Path:
    (out / "mr").mkdir(parents=True, exist_ok=True)
    (out / "mrs.ndjson").write_text("".join(json.dumps(m) + "\n" for m, _, _ in MRS))
    states = {}
    for data, state, text in MRS:
        iid = data["iid"]
        (out / "mr" / f"{iid}.json").write_text(json.dumps(data))
        (out / "mr" / f"{iid}-discussions.ndjson").write_text(
            "".join(json.dumps(d) + "\n" for d in THREADS.get(iid, [])))
        by = APPROVALS.get(iid, [])
        (out / "mr" / f"{iid}-approvals.json").write_text(json.dumps(
            {"approved": bool(by), "approvals_required": 1, "approvals_left": 0 if by else 1,
             "approved_by": [{"user": person(u)} for u in by]}))
        (out / "mr" / f"{iid}.diff").write_text(text)
        states[str(iid)] = state
    (out / "git.json").write_text(json.dumps(states))
    (out / "uploads" / UPLOAD).mkdir(parents=True, exist_ok=True)
    (out / "uploads" / UPLOAD / "bed-planner.png").write_bytes(png(480, 220))
    fetched = (datetime.now() - timedelta(minutes=40)).isoformat(timespec="seconds")
    (out / "meta.json").write_text(json.dumps({"project": "acme/garden-planner", "web_url": WEB,
                                               "state": "opened", "fetched_at": fetched, "count": len(MRS),
                                               "complete": True, "partial": False, "failures": []}))
    return render(snapshot.load(out))


def screenshots(index: Path, img_dir: Path) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)
    shots = [(index, "overview.png", "1400,900"), (index.parent / "mr" / "102.html", "mr-page.png", "1100,1500")]
    for page, name, size in shots:
        with tempfile.TemporaryDirectory() as profile:
            subprocess.run(["firefox", "--headless", "--no-remote", "--profile", profile, "--window-size", size,
                            "--screenshot", str(img_dir / name), page.as_uri()],
                           check=True, capture_output=True, timeout=90)
        print(img_dir / name)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out_dir", type=Path)
    p.add_argument("--screenshots", type=Path, metavar="IMG_DIR")
    args = p.parse_args()
    index = write_demo(args.out_dir.resolve())
    print(index)
    if args.screenshots:
        screenshots(index, args.screenshots.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
