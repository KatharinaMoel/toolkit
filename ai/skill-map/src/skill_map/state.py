"""What was published, and what changed since: diff, mark-published and the session
start check. Everything lives in the state folder; nothing else is written."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from .build import fingerprint
from .config import Config
from .discovery import World, discover
from .paths import state_dir, tilde

COMPARED = ("call", "kind", "place", "desc", "text", "text_sha256", "flags")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _names(keys: list[str]) -> str:
    keys = sorted(keys)
    return ", ".join(keys[:3]) + (f" +{len(keys) - 3}" if len(keys) > 3 else "")


# ---------- mark-published ----------
def mark_published(cfg: Config, log: Callable[[str], None]) -> int:
    folder = state_dir(cfg.profile)
    build, pub, prev = folder / "build", folder / "published", folder / "published.prev"
    if not (build / "inventory.json").is_file():
        log(f"skill-map: no build in {tilde(build)} - run skill-map build first")
        return 1
    inventory = _load(build / "inventory.json")
    fp, rows = fingerprint(discover(cfg))
    if fp != inventory.get("fingerprint"):
        log("skill-map: the set changed since the build; run build again before marking it published")
        return 1
    if prev.exists():
        log(f"removing {tilde(prev)}  (the publish before the last one)")
        shutil.rmtree(prev)
    if pub.exists():
        log(f"moving {tilde(pub)} -> {tilde(prev)}  (keep the last publish to go back to)")
        pub.rename(prev)
    log(f"copying {tilde(build)} -> {tilde(pub)}  (this build is what is online now)")
    shutil.copytree(build, pub)
    texts = {k: e["text_sha256"] for k, e in inventory["entries"].items() if e.get("text") == "shown"}
    record = {"fingerprint": fp, "set": rows, "texts": texts,
              "published": datetime.now().astimezone().isoformat(timespec="seconds")}
    log(f"writing {tilde(pub / 'fingerprint.json')}  (what the session start check compares against)")
    (pub / "fingerprint.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


# ---------- diff ----------
def _version_of(inv: dict, entry: dict) -> str:
    for g in inv.get("groups", []):
        if g["id"] == entry["group"] and g.get("origin"):
            return g["origin"].get("version") or ""
    return ""


def _print_text(key: str, entry: dict, text: str, out: Callable[[str], None]) -> None:
    out(f"==> {key} · {entry['path']}")
    out("──── begin ────")
    if text.endswith("\n"):
        out(text + f"──── end of {key} ────")
    else:
        out(text + f"\n──── end of {key} (no newline at end of file) ────")


def diff(texts: bool, log: Callable[[str], None], out: Callable[[str], None],
         profile: str | None = None) -> int:
    build, pub = state_dir(profile) / "build", state_dir(profile) / "published"
    if not (build / "inventory.json").is_file():
        log(f"skill-map: no build in {tilde(build)} - run skill-map build first")
        return 1
    log(f"comparing {tilde(build)} with {tilde(pub)}")
    new_inv = _load(build / "inventory.json")
    new_txt = _load(build / "wortlaut.json")
    if (pub / "inventory.json").is_file():
        old_inv = _load(pub / "inventory.json")
    else:
        out("never published: everything is new")
        old_inv = {"entries": {}, "groups": []}
    new, old = new_inv["entries"], old_inv["entries"]
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = {}
    for k in sorted(set(new) & set(old)):
        fields = [f for f in COMPARED if new[k].get(f) != old[k].get(f)]
        if _version_of(new_inv, new[k]) != _version_of(old_inv, old[k]):
            fields.append("version")
        if fields:
            changed[k] = fields
    out(f"new ({len(added)}): {', '.join(added) or '-'}")
    out(f"removed ({len(removed)}): {', '.join(removed) or '-'}")
    out(f"changed ({len(changed)}):" + ("" if changed else " -"))
    for k, fields in changed.items():
        out(f"  {k}: {', '.join(fields)}")
    page_changed = not (pub / "index.html").is_file() or (
        hashlib.sha256((build / "index.html").read_bytes()).digest()
        != hashlib.sha256((pub / "index.html").read_bytes()).digest())
    out(f"page: {'changed' if page_changed else 'unchanged'} (template and narrative)")
    missing = new_inv.get("narrative", {}).get("missing_keys", [])
    out(f"narrative: {len(missing)} missing key(s){': ' + ', '.join(missing) if missing else ''}")
    withheld = {k: v["withheld"] for k, v in new_txt["entries"].items() if "withheld" in v}
    out(f"withheld ({len(withheld)}):")
    for k, reason in withheld.items():
        out(f"  {k}: {reason}")
    if texts:
        for k in added + list(changed):
            e = new[k]                       # hand-written metadata goes online as data: read it too
            rb = e.get("runbook") if isinstance(e.get("runbook"), dict) else {}
            meta = [f"  desc: {e['desc']}"] if e.get("desc") else []
            if rb.get("tags"):
                meta.append(f"  tags: {', '.join(rb['tags'])}")
            if meta:
                out(f"==> {k} · metadata (published in inventory.json)")
                for line in meta:
                    out(line)
            t = new_txt["entries"].get(k, {})
            if new[k].get("text") == "shown" and "text" in t:
                _print_text(k, new[k], t["text"], out)
    return 0


# ---------- check ----------
def _group_name(key: str) -> str:
    return (key[6:] if key.startswith("agent:") else key).split(":")[0]


def check_message(cfg: Config) -> str | None:
    """The one line for the session start, or None when nothing changed. Reads no logs."""
    stored_file = state_dir(cfg.profile) / "published" / "fingerprint.json"
    hint = cfg.refresh_hint
    world: World = discover(cfg)
    if not stored_file.is_file():
        return f"{cfg.title}: noch nie veröffentlicht – {hint}"
    stored = _load(stored_file)
    fp, rows = fingerprint(world)
    cur = {r[0]: r for r in rows}
    old = {r[0]: r for r in stored.get("set", [])}
    parts = []
    if fp != stored.get("fingerprint"):
        added = [k for k in cur if k not in old]
        removed = [k for k in old if k not in cur]
        versions, other = {}, []
        for k in cur.keys() & old.keys():
            if cur[k][3] != old[k][3]:
                versions.setdefault(_group_name(k), f"{_group_name(k)} {old[k][3]}→{cur[k][3]}")
            elif cur[k] != old[k]:
                other.append(k)
        if added:
            parts.append(f"neu: {_names(added)}")
        if removed:
            parts.append(f"entfernt: {_names(removed)}")
        if versions or other:
            parts.append("geändert: " + ", ".join(sorted(versions.values()) + ([_names(other)] if other else [])))
    edited = 0
    for k, sha in (stored.get("texts") or {}).items():
        e = world.entries.get(k)
        if e is None or e.path is None:
            continue
        try:
            if hashlib.sha256(e.path.read_bytes()).hexdigest() != sha:
                edited += 1
        except OSError:
            continue       # cannot tell; the next build will
    texts = f"{edited} {'Text' if edited == 1 else 'Texte'} geändert"
    if parts:
        return f"{cfg.title} veraltet ({'; '.join(parts)})" + (f", {texts}" if edited else "") + f" – {hint}"
    if edited:
        return f"{cfg.title}: {texts} – {hint}"
    return None
