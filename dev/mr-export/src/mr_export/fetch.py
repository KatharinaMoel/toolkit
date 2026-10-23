"""Read merge requests from GitLab into a new snapshot folder. Only GET requests;
nothing on GitLab changes. An existing snapshot is never written to."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .runner import CommandError, Console, Runner
from .snapshot import MergeRequest, parse_ndjson, upload_refs


@dataclass
class FetchResult:
    path: Path
    count: int = 0
    notes: int = 0
    images: int = 0
    failures: list[str] = field(default_factory=list)


def new_snapshot_dir(root: Path, now: datetime) -> Path:
    """<root>/<YYYY-MM-DD_HHMM>, with -2, -3 ... when that minute is taken."""
    base = now.strftime("%Y-%m-%d_%H%M")
    candidate, n = root / base, 1
    while candidate.exists():
        n += 1
        candidate = root / f"{base}-{n}"
    return candidate


def fetch(runner: Runner, console: Console, root: Path, state: str, images: bool,
          now: datetime) -> FetchResult:
    project = json.loads(runner.glab_get(
        "projects/:id", "Ask GitLab which project this repository belongs to (also tests that the API answers)"))
    console.result(f"{project['path_with_namespace']} ({project['web_url']})")

    listing = runner.glab_get(
        f"projects/:id/merge_requests?state={state}&per_page=100",
        f"List the merge requests with state '{state}', all pages", paginate=True, ndjson=True)

    items = parse_ndjson(listing)   # before any folder exists: a bad answer leaves nothing behind
    snap = new_snapshot_dir(root, now)
    (snap / "mr").mkdir(parents=True)
    (snap / "mrs.ndjson").write_bytes(listing)
    console.result(f"{len(items)} merge requests -> {snap / 'mrs.ndjson'}")
    result = FetchResult(path=snap, count=len(items))
    failed_iids: list[int] = []

    def write_meta(complete: bool) -> None:
        """Written first with complete=false, so an interrupted read never looks finished."""
        meta = {
            "project": project["path_with_namespace"],
            "web_url": project["web_url"],
            "state": state,
            "fetched_at": now.isoformat(timespec="seconds"),
            "count": result.count,
            "complete": complete,
            "failures": result.failures,
            "failed_iids": failed_iids,
        }
        (snap / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    write_meta(False)

    mrs: list[MergeRequest] = []
    for i, item in enumerate(items):
        iid = item["iid"]
        shown = i == 0   # the first MR shows its three calls; the rest repeat them, one line each
        if i == 1:
            console.step(f"The same three reads for the other {len(items) - 1} merge requests, one line each")
        try:
            data = json.loads(runner.glab_get(
                f"projects/:id/merge_requests/{iid}",
                f"Read !{iid} in full: description, reviewers, head pipeline" if shown else None))
            (snap / "mr" / f"{iid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            raw = runner.glab_get(
                f"projects/:id/merge_requests/{iid}/discussions?per_page=100",
                f"Read the threads and comments of !{iid}, all pages" if shown else None,
                paginate=True, ndjson=True)
            discussions = parse_ndjson(raw)
            (snap / "mr" / f"{iid}-discussions.ndjson").write_bytes(raw)
            approvals = json.loads(runner.glab_get(
                f"projects/:id/merge_requests/{iid}/approvals",
                f"Read who approved !{iid} and how many approvals are missing" if shown else None))
            (snap / "mr" / f"{iid}-approvals.json").write_text(
                json.dumps(approvals, ensure_ascii=False, indent=1), encoding="utf-8")
        except (CommandError, json.JSONDecodeError, OSError) as e:
            failed_iids.append(iid)
            result.failures.append(f"!{iid}: {e}")
            console.note(f"!{iid} failed: {e}")
            continue
        notes = sum(len(d.get("notes", [])) for d in discussions)
        result.notes += notes
        mrs.append(MergeRequest(data=data, discussions=discussions, approvals=approvals))
        console.result(f"!{iid}: {len(discussions)} threads, {notes} notes")

    if images:
        refs = sorted({ref for mr in mrs for ref in upload_refs(mr)})
        for i, (secret, name) in enumerate(refs):
            if i == 1:
                console.step(f"The same download for the other {len(refs) - 1} files, one line each")
            target = snap / "uploads" / secret / name
            try:
                data = runner.glab_get(
                    f"projects/:id/uploads/{secret}/{quote(name, safe='')}",
                    "Download a file uploaded to a description or comment" if i == 0 else None)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except (CommandError, OSError) as e:
                result.failures.append(f"upload {secret}/{name}: {e}")
                console.note(f"upload {name} failed: {e}")
                continue
            result.images += 1
            console.result(f"{secret[:8]}…/{name} ({len(data) // 1024} KB)")
        if not refs:
            console.step("No uploaded files referenced in the texts")

    write_meta(True)
    return result
