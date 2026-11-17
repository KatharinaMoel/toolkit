"""The outcome of the newest fetch attempt, kept next to the snapshots:

<out_dir>/<repo>/last-run.json   {"time", "status", "snapshot", "count", "gaps", "reason"}

status: complete | partial (finished with gaps) | aborted (stopped half-way, the
snapshot stays unfinished) | unreachable (GitLab gave no list, no folder was made).
It is written on every attempt, so a run that left no usable snapshot is still
visible; 'latest' alone would quietly stay old."""
import json
import os
from datetime import datetime
from pathlib import Path

from . import retention

FILE = "last-run.json"
STATUSES = ("complete", "partial", "aborted", "unreachable")


def write(root: Path, time: datetime, status: str, snapshot: Path | None = None, count: int = 0,
          gaps: int = 0, reason: str | None = None) -> Path:
    if status not in STATUSES:
        raise ValueError(f"unknown run status: {status}")
    data = {"time": time.isoformat(timespec="seconds"), "status": status,
            "snapshot": snapshot.name if snapshot else None, "count": count, "gaps": gaps, "reason": reason}
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / ".last-run.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, root / FILE)   # never a half-written file
    return root / FILE


def read(root: Path) -> dict | None:
    try:
        data = json.loads((root / FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("status") in STATUSES else None


def _meta(path: Path) -> dict:
    try:
        return json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _hours_since(iso: str | None, now: datetime) -> float | None:
    try:
        then = datetime.fromisoformat(iso or "")
    except ValueError:
        return None
    if then.tzinfo is not None:
        then = then.astimezone().replace(tzinfo=None)
    return (now - then).total_seconds() / 3600


def check(root: Path, stale_after_hours: int, now: datetime) -> tuple[list[str], bool]:
    """Lines that say how complete and current the local copy is, and whether it can
    be relied on: 'latest' is complete, the last attempt was complete, and the read is
    younger than stale_after_hours."""
    items = retention.snapshots(root)
    shown = retention.current(root)
    last_complete = next((p for p, st in items if st == "complete"), None)
    last = read(root)
    problems: list[str] = []
    lines: list[str] = []
    if shown is None:
        lines.append("Latest:         none - run 'mr-export fetch' first")
        problems.append("no snapshot")
    else:
        meta, st = _meta(shown), retention.status(shown)
        age = _hours_since(meta.get("fetched_at"), now)
        age_text = f" ({age:.1f} h ago)" if age is not None else ""
        lines.append(f"Latest:         {shown.name} · {st} · {meta.get('count', '?')} MRs"
                     f" · read {meta.get('fetched_at', '?')}{age_text}")
        if st != "complete":
            problems.append(f"latest is {st}")
        if age is None or age > stale_after_hours:
            problems.append(f"latest is older than {stale_after_hours} h (stale_after_hours)")
        gaps = meta.get("failures") or []
        lines.append(f"Gaps in latest: {len(gaps)}" + (f" - {'; '.join(gaps[:5])}" if gaps else ""))
        if len(gaps) > 5:
            lines.append(f"                … and {len(gaps) - 5} more (see the top of index.html)")
    lines.append(f"Last complete:  {last_complete.name if last_complete else 'none'}")
    if last is None:
        lines.append("Last attempt:   unknown (no last-run.json yet)")
    else:
        detail = f" · {last.get('reason')}" if last.get("reason") else ""
        gaps_text = f" · {last.get('gaps')} gaps" if last.get("gaps") else ""
        lines.append(f"Last attempt:   {last.get('time')} · {last['status']}{gaps_text}{detail}")
        if last["status"] != "complete":
            problems.append(f"the last attempt was {last['status']}")
    lines.append("Verdict:        " + ("OK - the local copy is complete and current" if not problems
                                       else "NOT OK - " + "; ".join(problems)))
    return lines, not problems
