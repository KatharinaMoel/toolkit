"""Write inventory.json (metadata, usage) and wortlaut.json (texts 1:1) into a build
folder, and compute the fingerprint of the set of entries."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .discovery import World, discover
from .paths import claude_home, tilde
from .texts import withheld_text, text_for
from .usage import count_usage

TEXT_KINDS = ("skill", "command", "agent")       # kinds whose file text the page can show
USAGE_METHOD = ("Slash-Befehle aus <command-name> in Nutzernachrichten, Skills aus Skill-Aufrufen, "
                "Agenten aus Agent- und Task-Aufrufen; nur Haupt-Sessions, keine Subagenten-Logs; "
                "wiederholte Nachrichten einmal gezählt. Näherungswerte.")


def fingerprint(world: World) -> tuple[str, list[list[str]]]:
    """SHA-256 over the sorted (key, kind, place, version) lines; no usage, no texts."""
    rows = sorted([e.key, e.kind, e.place, e.version] for e in world.entries.values())
    data = "\n".join("\t".join(r) for r in rows).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest(), rows


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
        item = {"name": e.name, "call": e.call, "kind": e.kind, "group": e.group, "place": e.place,
                "desc": e.desc, "path": tilde(e.path) if e.path else None, "runbook": e.runbook,
                "source_note": e.source_note, "usage": {"count": count, "last": last},
                "text": "none", "text_sha256": None, "flags": sorted(e.flags)}
        if e.kind == "hook":
            item["matcher"] = e.extra.get("matcher", "")
        if e.kind in TEXT_KINDS and e.path is not None:
            try:
                r = text_for(key, e.path, cfg, e.source_path)
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
        entries[key] = item
    for key, item in entries.items():          # a runbook shows the usage of its command
        rb = item["runbook"]
        if item["kind"] == "runbook" and isinstance(rb, dict) and rb.get("command_entry") in entries:
            item["usage"] = dict(entries[rb["command_entry"]]["usage"])

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    inventory = {
        "schema": 1, "generated": now, "title": cfg.title, "fingerprint": fp,
        "usage": {"since": usage.since, "sessions": usage.sessions, "method": USAGE_METHOD,
                  "unmatched": usage.unmatched},
        "places": [vars(p) for p in world.places],
        "groups": [{"id": g.id, "title": g.title, "place": g.place, "origin": g.origin, "counts": g.counts}
                   for g in world.groups],
        "entries": entries,
        "narrative": {"missing_keys": []},
    }
    wortlaut = {"schema": 1, "generated": now, "entries": texts}
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "inventory.json", inventory, log, "the data the page shows")
    _write_json(out / "wortlaut.json", wortlaut, log, "the texts, unchanged or withheld")
    return out
