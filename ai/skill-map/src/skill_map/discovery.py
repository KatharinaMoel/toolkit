"""Find every skill, command, agent, runbook, hook, tool and builtin.

One function serves `build` and `check`, so the page and the session start hook can
never disagree about what exists. It reads only the head of each file (front matter
and kios marker, at most 4 KiB), never full texts or session logs.

Rules taken over from skill-show: a skill is found by its name: (else its folder),
skills come before commands and personal before project, plugins count only at the
installPath from installed_plugins.json, the plugin prefix is the name in plugin.json,
claude.ai plugins use the generation from their manifest (else the folder marked
.in_use), and names from manifests are checked before they become paths.
"""
import fnmatch
import glob
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .frontmatter import front_matter, kios_source
from .paths import claude_home, expand, tilde

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$", re.ASCII)


class DiscoveryError(Exception):
    """A required file is broken (installed_plugins.json); the message names it."""


@dataclass
class Entry:
    key: str
    name: str
    call: str | None
    kind: str                 # skill, command, agent, runbook, hook, tool, builtin
    group: str
    place: str
    desc: str
    path: Path | None
    runbook: dict | str | None = None
    source_note: str | None = None
    flags: set[str] = field(default_factory=set)
    version: str = ""         # the group's version for plugin and claude.ai entries
    source_path: Path | None = None   # the resolved kios source note
    extra: dict = field(default_factory=dict)


@dataclass
class Group:
    id: str
    title: str
    place: str
    origin: dict | None
    counts: dict[str, int]


@dataclass
class Place:
    id: str
    title: str
    path: str
    scope: str
    color: str


@dataclass
class World:
    places: list[Place]
    groups: list[Group]
    entries: dict[str, Entry]
    notes: list[str]


# Lane order, titles and colour tokens of the page; project:<n> lanes come after personal-skills.
LANES = [
    ("vault-runbooks", "Runbooks im Vault", "vault", "nur für dich · Quelle der Wahrheit"),
    ("personal-commands", "Persönliche Commands", "vault", "nur für dich · in jedem Projekt"),
    ("plugins", "Installierte Plugins", "plugin", "nur für dich · Aufruf mit Präfix plugin:"),
    ("claude-ai", "Von claude.ai synchronisiert", "synced", "aus deinem claude.ai-Konto · Aufruf mit Präfix"),
    ("personal-skills", "Eigene Skills", "vault", "nur für dich · in jedem Projekt"),
    ("toolkit", "toolkit", "cli", "Werkzeuge im Terminal"),
    ("hooks", "Hooks", "muted", "laufen automatisch bei Ereignissen"),
    ("builtins", "Eingebaut in Claude Code", "muted", "keine Datei · Text steckt im Programm"),
    ("managed", "Verwaltet (Organisation)", "muted", "von der Organisation vorgegeben"),
]
PROJECT_SCOPE = "für alle im Repo · nur in diesem Projekt"
INTERPRETERS = {"python", "python3", "bash", "sh", "node", "zsh", "uv", "uvx", "npx"}


def managed_dir() -> Path:
    return Path(os.environ.get("SKILL_MAP_MANAGED_DIR") or "/etc/claude-code")   # Linux; env for tests


class _Collector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.notes: list[str] = []
        self.entries: dict[str, Entry] = {}
        self.groups: dict[str, Group] = {}
        self.place_paths: dict[str, str] = {}
        self.project_titles: dict[str, str] = {}

    # ---------- helpers ----------
    def head(self, path: Path) -> bytes:
        try:
            with path.open("rb") as f:
                return f.read(4096)
        except OSError as e:
            self.notes.append(f"cannot read {tilde(path)} ({e.strerror}) - listed by its file name only")
            return b""

    def group(self, gid: str, title: str, place: str, origin: dict | None = None) -> None:
        self.groups.setdefault(gid, Group(gid, title, place, origin, {}))

    def add(self, entry: Entry) -> Entry:
        key = entry.key
        if key in self.entries:      # a second plugin with the same prefix, or two hooks alike
            entry.flags.add("shadowed")
            key = f"{key}@{entry.group}"
            n = 2
            while key in self.entries:
                key, n = f"{entry.key}@{entry.group}#{n}", n + 1
            entry.key = key
        self.entries[key] = entry
        return entry

    def note_skill_dirs(self, base: Path) -> list[Path]:
        if not base.is_dir():
            return []
        out = []
        for d in sorted(base.iterdir()):
            if d.name.startswith(".") or not d.is_dir() or not (d / "SKILL.md").is_file():
                continue
            out.append(d)
        return out

    # ---------- local skills and commands (bare names, with shadowing) ----------
    def local(self) -> None:
        cands = []   # (rank, place, kind, name, path, head)
        ch = claude_home()
        for d in self.note_skill_dirs(managed_dir() / ".claude" / "skills"):
            cands.append((10, "managed", "skill", d / "SKILL.md"))
        self.place_paths["managed"] = tilde(managed_dir() / ".claude" / "skills") + "/"
        for d in self.note_skill_dirs(ch / "skills"):
            if d.name != "synced":
                cands.append((20, "personal-skills", "skill", d / "SKILL.md"))
        self.place_paths["personal-skills"] = tilde(ch / "skills") + "/"
        for n, proj in enumerate(self.cfg.projects, start=1):
            place = f"project:{n}"
            self.project_titles[place] = proj.label
            self.place_paths[place] = tilde(proj.path / ".claude") + "/"
            for d in self.note_skill_dirs(proj.path / ".claude" / "skills"):
                cands.append((30 + n, place, "skill", d / "SKILL.md"))
        for f in self.command_files(ch / "commands"):
            cands.append((60, "personal-commands", "command", f))
        self.place_paths["personal-commands"] = tilde(ch / "commands") + "/"
        for n, proj in enumerate(self.cfg.projects, start=1):
            for f in self.command_files(proj.path / ".claude" / "commands"):
                cands.append((70 + n, f"project:{n}", "command", f))

        built = []
        for rank, place, kind, path in cands:
            data = self.head(path)
            fm = front_matter(data)
            if kind == "skill":
                name = fm.get("name") if isinstance(fm.get("name"), str) and fm.get("name") else path.parent.name
                base = name
            else:
                name = path.stem
                base = name if path.parent.name == "commands" else f"{path.parent.name}:{name}"
            desc = fm.get("description") if isinstance(fm.get("description"), str) else ""
            built.append((base, rank, Entry(base, name, "/" + base, kind, place, place, desc, path,
                                            source_note=kios_source(data))))
        for _, _, e in sorted(built, key=lambda t: (t[0], t[1])):
            if e.key in self.entries:
                e.flags.add("shadowed")
                e.key = f"{e.key}@{e.place}"
            self.entries[e.key] = e
            self.group(e.place, self.place_title(e.place), e.place)

        for f in sorted((ch / "agents").glob("*.md")) if (ch / "agents").is_dir() else []:
            fm = front_matter(self.head(f))
            name = fm.get("name") if isinstance(fm.get("name"), str) and fm.get("name") else f.stem
            desc = fm.get("description") if isinstance(fm.get("description"), str) else ""
            self.add(Entry(f"agent:{name}", name, name, "agent", "personal-skills", "personal-skills", desc, f))
            self.group("personal-skills", self.place_title("personal-skills"), "personal-skills")

    def command_files(self, base: Path) -> list[Path]:
        if not base.is_dir():
            return []
        files = sorted(p for p in base.glob("*.md") if not p.name.startswith("."))
        files += sorted(p for p in base.glob("*/*.md")
                        if not p.name.startswith(".") and not p.parent.name.startswith("."))
        return [p for p in files if p.is_file()]

    # ---------- plugins ----------
    def plugin_root(self, root: Path, gid: str, place: str, prefix: str, version: str, flags: set[str]) -> None:
        def entry(key, name, call, kind, path):
            fm = front_matter(self.head(path))
            desc = fm.get("description") if isinstance(fm.get("description"), str) else ""
            self.add(Entry(key, name, call, kind, gid, place, desc, path, flags=set(flags), version=version))

        for d in self.note_skill_dirs(root / "skills"):
            fm = front_matter(self.head(d / "SKILL.md"))
            name = fm.get("name") if isinstance(fm.get("name"), str) and fm.get("name") else d.name
            entry(f"{prefix}:{name}", name, f"/{prefix}:{name}", "skill", d / "SKILL.md")
        for kind, sub in (("command", "commands"), ("agent", "agents")):
            folder = root / sub
            for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
                if f.name.startswith("."):
                    continue
                name = f.stem
                if kind == "agent":
                    fm = front_matter(self.head(f))
                    if isinstance(fm.get("name"), str) and fm.get("name"):
                        name = fm["name"]
                    entry(f"agent:{prefix}:{name}", name, f"{prefix}:{name}", "agent", f)
                else:
                    entry(f"{prefix}:{name}", name, f"/{prefix}:{name}", "command", f)

    def plugin_json(self, root: Path) -> dict:
        p = root / ".claude-plugin" / "plugin.json"
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self.notes.append(f"cannot read {tilde(p)} - using the install key as the prefix")
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def vendor(meta: dict) -> str | None:
        a = meta.get("author")
        name = a.get("name") if isinstance(a, dict) else a      # never author.email
        return name if isinstance(name, str) and name else None

    @staticmethod
    def url(value) -> str | None:
        return value if isinstance(value, str) and value.startswith(("https://", "http://")) else None

    def prefix_of(self, meta: dict, fallback: str, where: Path) -> str:
        name = meta.get("name")
        if isinstance(name, str) and name:
            if NAME_RE.match(name):
                return name
            self.notes.append(f"unusable name in {tilde(where)}/.claude-plugin/plugin.json - using {fallback}")
        return fallback

    def plugins(self) -> None:
        ch = claude_home()
        self.place_paths["plugins"] = tilde(ch / "plugins") + "/"
        inst_file = ch / "plugins" / "installed_plugins.json"
        if inst_file.is_file():
            try:
                inst = json.loads(inst_file.read_text(encoding="utf-8"))
                plugins = inst["plugins"]
                if not isinstance(plugins, dict):
                    raise TypeError
            except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
                raise DiscoveryError(f"{inst_file}: cannot read the installed plugins ({type(e).__name__})") from e
            enabled = {}
            settings = ch / "settings.json"
            if settings.is_file():
                try:
                    enabled = json.loads(settings.read_text(encoding="utf-8")).get("enabledPlugins") or {}
                except (OSError, ValueError, AttributeError):
                    self.notes.append(f"cannot read {tilde(settings)} - enabledPlugins not checked")
            for key in sorted(plugins):
                items = plugins[key] if isinstance(plugins[key], list) else [plugins[key]]
                if not items or not isinstance(items[0], dict):
                    continue
                item = items[0]
                root = Path(str(item.get("installPath", "")))
                if not root.is_absolute() or not root.is_dir():
                    continue
                meta = self.plugin_json(root)
                prefix = self.prefix_of(meta, key.split("@")[0], root)
                version = item.get("version") or meta.get("version")
                when = item.get("installedAt")
                origin = {"type": "plugin", "plugin": prefix, "vendor": self.vendor(meta),
                          "version": version if isinstance(version, str) else None,
                          "marketplace": key.split("@", 1)[1] if "@" in key else None,
                          "installed": when[:10] if isinstance(when, str) else None,
                          "homepage": self.url(meta.get("homepage")), "repository": self.url(meta.get("repository"))}
                gid = f"plugin:{prefix}"
                if gid in self.groups:
                    gid = f"plugin:{prefix}@{origin['marketplace']}"
                self.group(gid, f"Plugin {prefix}", "plugins", origin)
                flags = {"disabled"} if isinstance(enabled, dict) and enabled.get(key) is False else set()
                self.plugin_root(root, gid, "plugins", prefix, origin["version"] or "", flags)

    def synced(self) -> None:
        ch = claude_home()
        self.place_paths["claude-ai"] = tilde(ch) + "/{skills,plugins}/synced/"
        prefix = self.cfg.synced_skill_prefix
        for bucket in sorted((ch / "skills" / "synced").glob("*/")) if (ch / "skills" / "synced").is_dir() else []:
            if bucket.name.startswith("."):
                continue
            names = self.manifest(bucket / "manifest.json", "skills")
            dirs = ([bucket / n for n in names] if names is not None
                    else [d for d in self.note_skill_dirs(bucket)])
            gid = f"claude-ai:{prefix}"
            self.group(gid, f"claude.ai {prefix}", "claude-ai",
                       {"type": "claude.ai", "plugin": prefix, "vendor": None, "version": None, "marketplace": None,
                        "installed": None, "homepage": None, "repository": None})
            for d in dirs:
                if not (d / "SKILL.md").is_file():
                    continue
                fm = front_matter(self.head(d / "SKILL.md"))
                name = fm.get("name") if isinstance(fm.get("name"), str) and fm.get("name") else d.name
                desc = fm.get("description") if isinstance(fm.get("description"), str) else ""
                self.add(Entry(f"{prefix}:{name}", name, f"/{prefix}:{name}", "skill", gid, "claude-ai", desc,
                               d / "SKILL.md"))
        base = ch / "plugins" / "synced"
        for bucket in sorted(base.glob("*/")) if base.is_dir() else []:
            if bucket.name.startswith("."):
                continue
            roots = []    # (folder, version)
            listed = self.manifest(bucket / "manifest.json", "plugins", with_generation=True)
            if listed is not None:
                for name, gen in listed:
                    if (bucket / f"{name}~g{gen}").is_dir():
                        roots.append((bucket / f"{name}~g{gen}", f"g{gen}"))
                    elif (bucket / name / ".in_use").is_file():
                        roots.append((bucket / name, ""))
                    else:
                        self.notes.append(f"claude.ai plugin {name}: no folder {name}~g{gen} and none marked .in_use - skipped")
            else:
                for d in sorted(bucket.iterdir()):
                    if d.is_dir() and (d / ".in_use").is_file():
                        m = re.search(r"~g(\d+)$", d.name)
                        roots.append((d, f"g{m.group(1)}" if m else ""))
                if not roots:
                    self.notes.append(f"claude.ai plugins in {tilde(bucket)}: no readable manifest.json and no folder marked .in_use - skipped")
            for root, version in roots:
                meta = self.plugin_json(root)
                pfx = self.prefix_of(meta, re.sub(r"~g\d+$", "", root.name), root)
                gid = f"claude-ai:{pfx}"
                self.group(gid, f"claude.ai {pfx}", "claude-ai",
                           {"type": "claude.ai", "plugin": pfx, "vendor": self.vendor(meta), "version": version or None,
                            "marketplace": None, "installed": None,
                            "homepage": self.url(meta.get("homepage")), "repository": self.url(meta.get("repository"))})
                self.plugin_root(root, gid, "claude-ai", pfx, version, set())

    def manifest(self, path: Path, key: str, with_generation: bool = False):
        """Names from a claude.ai manifest, checked like user names; None when unusable."""
        if not path.is_file():
            return None
        try:
            items = json.loads(path.read_text(encoding="utf-8"))[key]
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
            return None
        out = []
        for it in items if isinstance(items, list) else []:
            name = it.get("name") if isinstance(it, dict) else None
            if not isinstance(name, str) or not NAME_RE.match(name) or name in (".", ".."):
                self.notes.append(f"skipped an unusable name in {tilde(path)}")
                continue
            if with_generation:
                gen = it.get("generation")
                if not isinstance(gen, int):
                    self.notes.append(f"skipped {name} in {tilde(path)}: no generation")
                    continue
                out.append((name, gen))
            else:
                out.append(name)
        return out or None

    # ---------- runbooks, sources, hooks, tools, builtins ----------
    def runbooks(self) -> None:
        if self.cfg.vault is None:
            return
        folder = self.cfg.vault / "40-runbooks"
        self.place_paths["vault-runbooks"] = tilde(folder) + "/"
        for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            if f.name.startswith(("_", ".")):
                continue
            fm = front_matter(self.head(f))
            tags = fm.get("tags", [])
            tags = [tags] if isinstance(tags, str) and tags else (tags if isinstance(tags, list) else [])
            command = fm.get("command") if isinstance(fm.get("command"), str) and fm.get("command") else None
            status = fm.get("status") if isinstance(fm.get("status"), str) else None
            area = next((self.cfg.areas[t] for t in tags if t in self.cfg.areas), None)
            title = fm.get("title") if isinstance(fm.get("title"), str) else ""
            key = f"runbook:{f.stem}"
            cmd = self.entries.get(command) if command else None
            linked = (cmd is not None and cmd.kind == "command" and cmd.place == "personal-commands"
                      and cmd.source_note == f"40-runbooks/{f.name}")
            flags = {"draft"} if status == "entwurf" else set()
            if not linked:
                flags.add("no-command")
            self.add(Entry(key, f.stem, "/" + command if command else None, "runbook", "vault-runbooks",
                           "vault-runbooks", title, f, flags=flags,
                           runbook={"status": status, "tags": tags, "area": area, "command": command,
                                    "command_entry": command if linked else None}))
            self.group("vault-runbooks", self.place_title("vault-runbooks"), "vault-runbooks")
            if linked:
                cmd.runbook = key
                if status == "entwurf":
                    cmd.flags.add("draft")

    def sources(self) -> None:
        roots = ([self.cfg.vault] if self.cfg.vault else []) + list(self.cfg.source_roots)
        if not roots:
            return          # nothing configured: unknown, not missing
        for e in self.entries.values():
            if not e.source_note:
                continue
            hit = next((r / e.source_note for r in roots if (r / e.source_note).is_file()), None)
            if hit is None:
                e.flags.add("source-missing")
            else:
                e.source_path = hit

    def hooks(self) -> None:
        files = [claude_home() / "settings.json"] + [p.path / ".claude" / "settings.json" for p in self.cfg.projects]
        self.place_paths["hooks"] = tilde(files[0])
        for sf in files:
            if not sf.is_file():
                continue
            try:
                hooks = json.loads(sf.read_text(encoding="utf-8")).get("hooks") or {}
            except (OSError, ValueError, AttributeError):
                self.notes.append(f"cannot read the hooks in {tilde(sf)}")
                continue
            for event in sorted(hooks) if isinstance(hooks, dict) else []:
                for block in hooks[event] if isinstance(hooks[event], list) else []:
                    if not isinstance(block, dict):
                        continue
                    for h in block.get("hooks") or []:
                        if not isinstance(h, dict) or h.get("type") != "command" or not isinstance(h.get("command"), str):
                            continue
                        words = h["command"].split()
                        if not words:
                            continue
                        word = words[0]
                        if Path(word).name in INTERPRETERS and len(words) > 1:
                            word = words[1]
                        path = expand(word)
                        desc = h.get("statusMessage") if isinstance(h.get("statusMessage"), str) else ""
                        self.add(Entry(f"hook:{event}:{path.name}", path.name, event, "hook", "hooks", "hooks", desc,
                                       path, extra={"matcher": block.get("matcher") or ""}))
                        self.group("hooks", self.place_title("hooks"), "hooks")

    def tools(self) -> None:
        seen = set()
        for pattern in self.cfg.tools:
            self.place_paths.setdefault("toolkit", tilde(pattern))
            for d in sorted(glob.glob(pattern)):
                d = Path(d)
                exe = d / d.name
                if not d.is_dir() or not exe.is_file() or not os.access(exe, os.X_OK) or d.name in seen:
                    continue
                seen.add(d.name)
                desc = ""
                readme = d / "README.md"
                if readme.is_file():
                    first = self.head(readme).decode("utf-8", "replace").splitlines()[:1]
                    if first and first[0].startswith("# ") and " — " in first[0]:
                        desc = first[0].split(" — ", 1)[1].strip()
                self.add(Entry(f"tool:{d.name}", d.name, d.name, "tool", "toolkit", "toolkit", desc, exe))
                self.group("toolkit", self.place_title("toolkit"), "toolkit")

    def builtins(self) -> None:
        self.place_paths["builtins"] = ""
        for name, desc in sorted(self.cfg.builtins.items()):
            self.add(Entry(f"builtin:{name}", name, "/" + name, "builtin", "builtins", "builtins", desc, None))
            self.group("builtins", self.place_title("builtins"), "builtins")

    # ---------- result ----------
    def place_title(self, pid: str) -> str:
        if pid in self.project_titles:
            return self.project_titles[pid]
        return next(t for i, t, _, _ in LANES if i == pid)

    def world(self) -> World:
        for k in [k for k in self.entries if any(fnmatch.fnmatchcase(k, p) for p in self.cfg.hide)]:
            del self.entries[k]
        used = {e.place for e in self.entries.values()}
        order = [lane[0] for lane in LANES]
        projects = sorted((p for p in used if p.startswith("project:")), key=lambda p: int(p.split(":")[1]))
        order = order[:5] + projects + order[5:]
        places = []
        for pid in order:
            if pid not in used:
                continue
            if pid.startswith("project:"):
                places.append(Place(pid, self.project_titles[pid], self.place_paths.get(pid, ""), PROJECT_SCOPE, "repo"))
            else:
                _, title, color, scope = next(lane for lane in LANES if lane[0] == pid)
                places.append(Place(pid, title, self.place_paths.get(pid, ""), scope, color))
        groups = []
        for g in self.groups.values():
            members = [e for e in self.entries.values() if e.group == g.id]
            if not members and g.place not in ("plugins", "claude-ai"):   # an empty plugin is still installed
                continue
            g.counts = {k: sum(1 for e in members if e.kind == k) for k in ("skill", "command", "agent")}
            groups.append(g)
        groups.sort(key=lambda g: (order.index(g.place), g.title))
        return World(places, groups, dict(sorted(self.entries.items())), self.notes)


def discover(cfg: Config) -> World:
    c = _Collector(cfg)
    c.local()
    c.plugins()
    c.synced()
    c.runbooks()
    c.sources()
    c.hooks()
    c.tools()
    c.builtins()
    return c.world()
