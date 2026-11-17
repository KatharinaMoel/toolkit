"""Read merge requests from GitLab into a new snapshot folder. Only GET requests;
nothing on GitLab changes. An existing snapshot is never written to."""
import fcntl
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import gitstate, lastrun, share
from .runner import CommandError, CommandTimeout, Console, Runner
from .snapshot import MergeRequest, mr_number, parse_ndjson, upload_refs


class FetchLocked(Exception):
    """Another fetch for the same repository is running."""


class FetchAborted(CommandError):
    """GitLab stopped answering during a run; the snapshot stays unfinished."""


class Stopped(Exception):
    """The run was told to stop (SIGTERM, e.g. by the timer's time limit). Not a
    CommandError, so no per-item handler swallows it."""


# A GitLab that accepts connections but never answers would otherwise cost the full
# runner timeout per request, for every MR and every upload.
TIMEOUTS_IN_A_ROW = 3


class TimeoutGuard:
    """Counts requests that timed out one after the other; any answer, even an error,
    resets the count."""

    def __init__(self, limit: int = TIMEOUTS_IN_A_ROW):
        self.limit = limit
        self.in_a_row = 0

    def answered(self) -> None:
        self.in_a_row = 0

    def failed(self, error: Exception) -> str | None:
        """Returns the reason to stop the run, or None to go on."""
        self.in_a_row = self.in_a_row + 1 if isinstance(error, CommandTimeout) else 0
        if self.in_a_row < self.limit:
            return None
        return f"GitLab does not answer: {self.in_a_row} requests in a row timed out"


@dataclass
class FetchResult:
    path: Path
    count: int = 0
    notes: int = 0
    images: int = 0
    images_reused: int = 0
    shared_files: int = 0
    shared_bytes: int = 0
    failures: list[str] = field(default_factory=list)


def new_snapshot_dir(root: Path, now: datetime) -> Path:
    """<root>/<YYYY-MM-DD_HHMM>, with -2, -3 ... when that minute is taken."""
    base = now.strftime("%Y-%m-%d_%H%M")
    candidate, n = root / base, 1
    while candidate.exists():
        n += 1
        candidate = root / f"{base}-{n}"
    return candidate


def collect_git_state(runner: Runner, console: Console, mrs: list[MergeRequest],
                      emergency: dict[str, str], snap: Path) -> list[str]:
    """Writes git.json (per MR: is its change in the target / in the emergency branch)
    and mr/<iid>.diff. Returns failures; when Git cannot reach the server, one failure
    and no git.json."""
    try:
        on_server = gitstate.remote_heads(runner)
        targets = {m.data.get("target_branch") for m in mrs} - {None}
        branches = sorted(b for b in targets | set(emergency.values()) if b in on_server)
        console.result(f"{len(on_server)} branches; reading {', '.join(branches) or 'none'}")
        gitstate.fetch_refs(runner, branches)
    except CommandError as e:
        console.note(f"Git over SSH failed: {e}")
        return [f"git: {e}"]
    console.step(f"For each MR: is its change already in its target branch, and its diff ({len(mrs)} MRs)")
    states: dict[str, dict] = {}
    failures: list[str] = []
    for mr in mrs:
        target, head = mr.data.get("target_branch"), mr.data.get("sha") or gitstate.mr_ref(mr.iid)
        if target not in branches:
            states[str(mr.iid)] = {"target": "unknown", "emergency": None, "emergency_branch": None}
            continue
        state = {"target": gitstate.merge_state(runner, head, gitstate.head_ref(target)),
                 "emergency": None, "emergency_branch": None}
        branch = emergency.get(target)
        if state["target"] in ("no", "conflict") and branch in branches:
            state["emergency"] = gitstate.merge_state(runner, head, gitstate.head_ref(branch))
            state["emergency_branch"] = branch
        states[str(mr.iid)] = state
        if state["target"] == "unknown":   # head not fetchable (force-pushed, deleted): no diff
            continue
        try:
            (snap / "mr" / f"{mr.iid}.diff").write_text(
                gitstate.diff_text(runner, gitstate.head_ref(target), head), encoding="utf-8")
        except CommandError as e:
            failures.append(f"diff !{mr.iid}: {e}")
    (snap / "git.json").write_text(json.dumps(states, indent=1), encoding="utf-8")
    counts = {k: sum(1 for v in states.values() if v["target"] == k)
              for k in ("yes", "content", "no", "conflict", "unknown")}
    console.result(", ".join(f"{n} {k}" for k, n in counts.items() if n))
    return failures


def fetch(runner: Runner, console: Console, root: Path, state: str, images: bool,
          now: datetime, emergency: dict[str, str] | None = None) -> FetchResult:
    """One fetch per repository at a time: a second one stops with FetchLocked."""
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".fetch.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FetchLocked(f"another mr-export fetch is running for {root}") from None
        progress: dict = {}
        try:
            result = _fetch(runner, console, root, state, images, now, emergency or {}, progress)
        except BaseException as e:
            done: FetchResult | None = progress.get("result")
            unreachable = done is None and isinstance(e, (CommandError, ValueError))
            lastrun.write(root, now, "unreachable" if unreachable else "aborted",
                          done.path if done else None, done.count if done else 0,
                          len(done.failures) if done else 0,
                          str(e) or ("interrupted" if isinstance(e, KeyboardInterrupt) else type(e).__name__))
            raise
        lastrun.write(root, now, "partial" if result.failures else "complete", result.path, result.count,
                      len(result.failures))
        return result


def _fetch(runner: Runner, console: Console, root: Path, state: str, images: bool,
           now: datetime, emergency: dict[str, str], progress: dict) -> FetchResult:
    project = json.loads(runner.glab_get(
        "projects/:id", "Ask GitLab which project this repository belongs to (also tests that the API answers)"))
    console.result(f"{project['path_with_namespace']} ({project['web_url']})")

    listing = runner.glab_get(
        f"projects/:id/merge_requests?state={state}&per_page=100",
        f"List the merge requests with state '{state}', all pages", paginate=True, ndjson=True)

    items = parse_ndjson(listing)   # before any folder exists: a bad answer leaves nothing behind
    previous = share.previous_complete(root)   # looked up before the new folder exists
    snap = new_snapshot_dir(root, now)
    (snap / "mr").mkdir(parents=True)
    (snap / "mrs.ndjson").write_bytes(listing)
    console.result(f"{len(items)} merge requests -> {snap / 'mrs.ndjson'}")
    result = FetchResult(path=snap, count=len(items))
    progress["result"] = result
    failed_iids: list[int] = []
    guard = TimeoutGuard()

    def write_meta(complete: bool, aborted: str | None = None) -> None:
        """Written first with complete=false, so an interrupted read never looks finished."""
        meta = {
            "project": project["path_with_namespace"],
            "web_url": project["web_url"],
            "state": state,
            "fetched_at": now.isoformat(timespec="seconds"),
            "count": result.count,
            "complete": complete,
            "partial": bool(result.failures),
            "failures": result.failures,
            "failed_iids": failed_iids,
        }
        if aborted:
            meta["aborted"] = aborted
        (snap / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    write_meta(False)

    def give_up_if_unanswered(error: Exception) -> None:
        reason = guard.failed(error)
        if reason:
            write_meta(False, aborted=reason)
            console.note(f"{reason} - stopping; this snapshot stays unfinished, 'latest' does not move")
            raise FetchAborted(reason)

    mrs: list[MergeRequest] = []
    for i, item in enumerate(items):
        try:
            iid = mr_number(item.get("iid"))
        except ValueError as e:
            result.failures.append(str(e))
            console.note(f"skipped: {e}")
            continue
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
            give_up_if_unanswered(e)
            continue
        guard.answered()
        notes = sum(len(d.get("notes", [])) for d in discussions)
        result.notes += notes
        mrs.append(MergeRequest(data=data, discussions=discussions, approvals=approvals))
        console.result(f"!{iid}: {len(discussions)} threads, {notes} notes")

    try:
        members = runner.glab_get("projects/:id/members/all?per_page=100",
                                  "Read the project members and their roles", paginate=True, ndjson=True)
        parse_ndjson(members)
        (snap / "members.ndjson").write_bytes(members)
        console.result(f"{len(parse_ndjson(members))} members")
    except (CommandError, json.JSONDecodeError) as e:
        result.failures.append(f"members: {e}")
        console.note(f"members failed: {e}")

    try:
        raw = runner.glab_get("projects/:id/labels?per_page=100",
                              "Read the project's labels and their priorities (for the order of the overview)",
                              paginate=True, ndjson=True)
        labels = [{"name": str(lb["name"]), "priority": lb.get("priority")} for lb in parse_ndjson(raw)]
        (snap / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
        console.result(f"{len(labels)} labels, {sum(1 for lb in labels if lb['priority'] is not None)} with a priority")
    except (CommandError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        # Not a gap: every MR is complete; the overview falls back to top_labels.
        console.note(f"labels could not be read, the overview sorts by top_labels instead: {e}")

    if images:
        refs = sorted({ref for mr in mrs for ref in upload_refs(mr)})
        known = previous / "uploads" if previous else None
        if known is not None and any(share.existing_file(known / s / n) for s, n in refs):
            console.step(f"Files already in {previous.name} are taken from there (hard link), not downloaded again")
        downloads = 0
        for secret, name in refs:
            target = snap / "uploads" / secret / name
            if known is not None and share.existing_file(known / secret / name):
                try:
                    share.link_or_copy(known / secret / name, target)
                except OSError as e:
                    result.failures.append(f"upload {secret}/{name}: {e}")
                    console.note(f"upload {name} failed: {e}")
                    continue
                result.images += 1
                result.images_reused += 1
                continue
            downloads += 1
            if downloads == 2:
                console.step("The same download for the other new files, one line each")
            try:
                data = runner.glab_get(
                    f"projects/:id/uploads/{secret}/{quote(name, safe='')}",
                    "Download a file uploaded to a description or comment" if downloads == 1 else None)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except (CommandError, OSError) as e:
                result.failures.append(f"upload {secret}/{name}: {e}")
                console.note(f"upload {name} failed: {e}")
                give_up_if_unanswered(e)
                continue
            guard.answered()
            result.images += 1
            console.result(f"{secret[:8]}…/{name} ({len(data) // 1024} KB)")
        if not refs:
            console.step("No uploaded files referenced in the texts")

    console.step("Read over Git (SSH) what is already merged, and every MR's diff")
    result.failures += collect_git_state(runner, console, mrs, emergency, snap)

    if previous is not None:
        console.step(f"Store files that did not change since {previous.name} only once (hard links)")
        shared = share.share_unchanged(snap, previous)
        result.shared_files, result.shared_bytes = shared.files, shared.bytes
        console.result(f"{shared.files} files shared, {shared.bytes // 1024} KB not stored twice")

    write_meta(True)
    return result
