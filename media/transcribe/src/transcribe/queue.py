"""Resumable work queue: one JSON state file, one entry per (feed, guid).

Status per entry: pending -> running -> done | failed.
- Every change is saved atomically (temp file + rename), so a kill at any
  moment leaves either the old or the new state on disk, never half of one.
- An entry left `running` by a killed process goes back to `pending` - the
  killed attempt counts, so an episode that crashes the process every time
  ends as `failed` after MAX_ATTEMPTS instead of blocking every restart.
- `done` counts only while its output exists and carries the same sha256 the
  queue recorded (audio for ASR entries, transcript for publisher entries);
  otherwise the entry is redone.
- A lock file stops two runs from working the same queue.
"""

import fcntl
import json
import os
import tempfile
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import markdown

MAX_ATTEMPTS = 3
STATUSES = ("pending", "running", "done", "failed")


class QueueError(Exception):
    pass


def key(feed_url, guid):
    return f"{feed_url}#{guid}"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Queue:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = data["entries"]
                if not isinstance(self.entries, dict):
                    raise TypeError("entries ist kein Objekt")
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise QueueError(f"Queue-Datei {self.path} ist beschädigt ({exc}); "
                                 "sie wird nicht überschrieben - bitte prüfen oder verschieben") from None
            for k, e in self.entries.items():
                if (not isinstance(e, dict) or e.get("status") not in STATUSES
                        or not isinstance(e.get("attempts"), int) or "feed_url" not in e):
                    raise QueueError(f"Queue-Datei {self.path}: Eintrag {k!r} ist unvollständig "
                                     "(status/attempts/feed_url) - bitte prüfen")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": self.entries}, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)  # make the rename itself durable across a power loss
            finally:
                os.close(dir_fd)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def get(self, k):
        return self.entries[k]

    def add(self, fields):
        k = key(fields["feed_url"], fields["guid"])
        if k in self.entries:
            return False
        self.entries[k] = {**fields, "status": "pending", "attempts": 0, "error": None,
                           "output": None, "audio_sha256": None, "timings": {},
                           "added_at": now(), "updated_at": now()}
        return True

    def _set(self, k, **changes):
        self.entries[k].update(changes, updated_at=now())

    def mark_running(self, k):
        e = self.entries[k]
        self._set(k, status="running", attempts=e["attempts"] + 1, error=None)

    def mark_done(self, k, result):
        timings = {t: result[t] for t in ("audio_seconds", "compute_seconds", "download_seconds")
                   if t in result}
        self._set(k, status="done", error=None, output=result["output"],
                  backend=result.get("backend"), fallback_reason=result.get("fallback_reason"),
                  audio_sha256=result.get("audio_sha256"), audio_bytes=result.get("audio_bytes"),
                  transcript_sha256=result.get("transcript_sha256"), timings=timings)

    def mark_failed(self, k, error):
        self._set(k, status="failed", error=error)

    def recover(self):
        """Entries a killed run left `running` go back to `pending` - or to `failed`
        once the killed attempts reach MAX_ATTEMPTS (the kill counts as an attempt)."""
        stale = [k for k, e in self.entries.items() if e["status"] == "running"]
        for k in stale:
            n = self.entries[k]["attempts"]
            if n >= MAX_ATTEMPTS:
                self._set(k, status="failed", error=f"abgebrochen (Absturz/Kill) nach {n} Versuchen")
            else:
                self._set(k, status="pending", error="unterbrochen (Prozess beendet) - neu eingeplant")
        return stale

    def retry(self, keys, force_asr=False):
        """Failed entries back to pending with a fresh attempt budget."""
        for k in keys:
            extra = {"force_asr": True} if force_asr else {}
            self._set(k, status="pending", attempts=0, error=None, **extra)

    def ordered(self):
        return sorted(self.entries.items(), key=lambda kv: (kv[1]["feed_url"], kv[1].get("index") or 0))


def output_is_valid(entry):
    out = entry.get("output")
    if not out or not Path(out).is_file():
        return False
    field = "transcript_sha256" if entry.get("backend") == markdown.PUBLISHER else "audio_sha256"
    return markdown.read_frontmatter(out).get(field) == entry.get(field)


def plan(state):
    """Keys to work, in order; done entries with missing/foreign output are reopened."""
    todo, reopened = [], []
    for k, e in state.ordered():
        if e["status"] == "done":
            if output_is_valid(e):
                continue
            state._set(k, status="pending", error="Ausgabe fehlt oder sha256 passt nicht - wird neu erstellt")
            reopened.append(k)
        if e["status"] == "pending" or (e["status"] == "failed" and e["attempts"] < MAX_ATTEMPTS):
            todo.append(k)
    return todo, reopened


@contextmanager
def locked(state_path):
    lock_path = Path(str(state_path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QueueError("die Queue ist gerade gesperrt - ein 'transcribe queue run' oder 'queue add' "
                             f"läuft (Sperre {lock_path}); später noch einmal") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def run(state_path, work, max_items=None, ui=None, on_plan=None):
    """Work the queue. `work(entry) -> result dict` does one episode.

    Returns one report row per entry worked in this run (empty if nothing to do).
    """
    report = []
    with locked(state_path):
        state = Queue(state_path)
        stale = state.recover()
        todo, reopened = plan(state)
        if stale or reopened:
            state.save()
        if on_plan:
            on_plan(state, stale, reopened, todo)
        if max_items is not None:
            todo = todo[:max_items]
        for k in todo:
            state.mark_running(k)
            state.save()
            entry = dict(state.get(k))
            started = time.monotonic()
            try:
                result = work(entry)
            except KeyboardInterrupt:
                state._set(k, status="pending", error="abgebrochen (Strg-C) - neu eingeplant")
                state.save()
                raise
            except Exception as exc:  # one broken episode must not stop a multi-day run
                detail = traceback.format_exception_only(type(exc), exc)[-1].strip()
                state.mark_failed(k, detail)
                state.save()
                report.append({"index": entry.get("index"), "title": entry.get("title"), "status": "failed",
                               "backend": None,
                               "audio_seconds": None, "compute_seconds": None,
                               "wall_seconds": time.monotonic() - started, "error": detail})
                if ui:
                    ui.warn(f"Episode {entry.get('index')} fehlgeschlagen: {detail}")
                continue
            state.mark_done(k, result)
            state.save()
            report.append({"index": entry.get("index"), "title": entry.get("title"), "status": "done",
                           "backend": result.get("backend"),
                           "audio_seconds": result.get("audio_seconds"),
                           "compute_seconds": result.get("compute_seconds"),
                           "wall_seconds": time.monotonic() - started, "error": None})
    return report
