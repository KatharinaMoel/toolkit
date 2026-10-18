"""Write inventory.json (metadata, usage) and wortlaut.json (texts 1:1) into a build
folder, and compute the fingerprint of the set of entries."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .discovery import World, discover
from .narrative import missing_keys, read_narrative, render_page
from .paths import UUID_RE, claude_home, tilde
from .texts import is_classified, text_for, withheld_text
from .usage import count_usage

TEMPLATE = Path(__file__).resolve().parents[2] / "page" / "template.html"
TEXT_KINDS = ("skill", "command", "agent")       # kinds whose file text the page can show
USAGE_METHOD = ("Slash-Befehle aus <command-name> in Nutzernachrichten, Skills aus Skill-Aufrufen, "
                "Agenten aus Agent- und Task-Aufrufen; nur Haupt-Sessions, keine Subagenten-Logs; "
                "wiederholte Nachrichten einmal gezählt. Näherungswerte.")


def fingerprint(world: World) -> tuple[str, list[list[str]]]:
    """SHA-256 over the sorted (key, kind, place, version) lines; no usage, no texts."""
    rows = sorted([e.key, e.kind, e.place, e.version] for e in world.entries.values())
    data = "\n".join("\t".join(r) for r in rows).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest(), rows


def _head(path: Path) -> bytes | None:
    """The first 4 KiB, or None when the file cannot be read."""
    try:
        with path.open("rb") as f:
            return f.read(4096)
    except OSError:
        return None


def _classified(e) -> bool:
    """The entry's own file or its kios source note is classified. Fails closed: a
    file that cannot be read counts as classified. Hooks, tools and builtins have no
    front matter of their own, so only skills, commands, agents and runbooks count."""
    if e.kind not in TEXT_KINDS + ("runbook",):
        return False
    for p in (e.path, e.source_path):
        if p is None:
            continue
        head = _head(p)
        if head is None or is_classified(head):
            return True
    return False


def _clean(text):
    """Free text from front matter: account ids replaced, as in paths."""
    return UUID_RE.sub("<konto>", text) if isinstance(text, str) else text


def _scrub(value):
    """Account ids out of every string in an output structure (keys stay)."""
    if isinstance(value, str):
        return UUID_RE.sub("<konto>", value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _write_json(path: Path, data, log: Callable[[str], None], why: str) -> None:
    log(f"writing {tilde(path)}  ({why})")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build(cfg: Config, out: Path, log: Callable[[str], None]) -> Path:
    ch = claude_home()
    log(f"reading {tilde(ch / 'plugins/installed_plugins.json')}  (which plugin versions are installed)")
    log(f"reading {tilde(ch)}/{{commands,skills,agents,plugins,settings.json}}  (skills, commands, agents, hooks)")
    if cfg.vault:
        log(f"reading {tilde(cfg.vault / '40-runbooks')}  (runbooks, front matter only)")
    world = discover(cfg)
    for note in world.notes:
        log(f"note: {note}")
    log(f"reading {tilde(ch / 'projects')}/*/*.jsonl  (usage counts; nothing else is kept)")
    usage = count_usage(world, ch / "projects")
    if usage.skipped:
        log(f"note: {usage.skipped} log line(s) could not be parsed and were skipped")

    fp, _ = fingerprint(world)
    entries, texts = {}, {}
    for key, e in world.entries.items():
        count, last = usage.counts.get(key, (0, None))
        source_unknown = e.source_note is not None and e.source_path is None
        classified = (_classified(e) or source_unknown     # unknown classification counts as classified
                      or key in cfg.withhold_text)          # what made the text private is usually in the description too
        desc, runbook = _clean(e.desc), e.runbook
        if isinstance(runbook, dict):
            runbook = dict(runbook, tags=[_clean(t) for t in runbook.get("tags") or []])
        if classified:          # nothing written by hand in a classified file leaves it
            desc = ""
            if isinstance(runbook, dict):
                runbook = dict(runbook, tags=[], area=None)
        item = {"name": e.name, "call": e.call, "kind": e.kind, "group": e.group, "place": e.place,
                "desc": desc, "path": tilde(e.path) if e.path else None, "runbook": runbook,
                "source_note": e.source_note, "usage": {"count": count, "last": last},
                "text": "none", "text_sha256": None, "flags": sorted(e.flags)}
        if e.kind == "hook":
            item["matcher"] = e.extra.get("matcher", "")
        if e.kind in TEXT_KINDS and e.path is not None:
            try:
                r = text_for(key, e.path, cfg, e.source_path, source_unknown=source_unknown)
            except OSError:
                item["text"] = "withheld"
                item["flags"] = sorted(e.flags | {"withheld"})
                texts[key] = {"withheld": withheld_text("Datei nicht lesbar", e.path)}
            else:
                item["text"], item["text_sha256"] = r.status, r.sha256
                if r.status == "shown":
                    texts[key] = {"text": r.text}
                else:
                    item["flags"] = sorted(e.flags | {"withheld"})
                    texts[key] = {"withheld": r.withheld}
        entries[key] = _scrub(item)
    for key, item in entries.items():          # a runbook shows the usage of its command
        rb = item["runbook"]
        if item["kind"] == "runbook" and isinstance(rb, dict) and rb.get("command_entry") in entries:
            item["usage"] = dict(entries[rb["command_entry"]]["usage"])

    log(f"reading {tilde(cfg.narrative)}  (your own texts for the page, if the file exists)")
    narrative = read_narrative(cfg.narrative)
    for note in narrative.notes:
        log(note)
    missing = missing_keys(narrative, set(entries), {p.id for p in world.places})
    if missing:
        n = len(missing)
        what = "1 reference to a missing entry" if n == 1 else f"{n} references to missing entries"
        log(f"narrative: {what}: {', '.join(missing)}")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    inventory = {
        "schema": 1, "generated": now, "title": cfg.title, "refresh_hint": cfg.refresh_hint, "fingerprint": fp,
        "usage": {"since": usage.since, "sessions": usage.sessions, "method": USAGE_METHOD,
                  "unmatched": _scrub(usage.unmatched)},
        "places": _scrub([vars(p) for p in world.places]),
        "groups": _scrub([{"id": g.id, "title": g.title, "place": g.place, "origin": g.origin, "counts": g.counts}
                          for g in world.groups]),
        "entries": entries,
        "narrative": {"missing_keys": missing},
    }
    wortlaut = {"schema": 1, "generated": now, "entries": texts}
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "inventory.json", inventory, log, "the data the page shows")
    _write_json(out / "wortlaut.json", wortlaut, log, "the texts, unchanged or withheld")
    template = TEMPLATE.read_text(encoding="utf-8")
    log(f"writing {tilde(out / 'index.html')}  (the page; it loads the two files next to it)")
    (out / "index.html").write_text(render_page(template, cfg.title, narrative, None), encoding="utf-8")
    log(f"writing {tilde(out / 'skill-map.html')}  (the same page with the data inside; opens from disk)")
    (out / "skill-map.html").write_text(render_page(template, cfg.title, narrative, (inventory, wortlaut)),
                                        encoding="utf-8")
    return out
