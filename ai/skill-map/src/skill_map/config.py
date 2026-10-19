"""The optional config file (TOML). Every key is optional: without a file the tool
shows Claude Code's own places. Personal sources are switched on here."""
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .paths import config_dir, expand


class ConfigError(Exception):
    """Invalid TOML or a key with the wrong type; the message names the file and key."""


@dataclass
class Project:
    path: Path
    label: str


@dataclass
class Config:
    vault: Path | None = None                  # notes vault with 40-runbooks/ and kios source notes
    projects: list[Project] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)          # glob patterns of tool folders
    builtins: dict[str, str] = field(default_factory=dict)  # bundled command name -> description
    withhold_text: dict[str, str | None] = field(default_factory=dict)  # key -> reason (None: default)
    hide: list[str] = field(default_factory=list)            # keys or glob patterns over keys
    areas: dict[str, str] = field(default_factory=dict)      # runbook tag -> area shown on the page
    source_roots: list[Path] = field(default_factory=list)
    source_prefixes: dict[str, Path] = field(default_factory=dict)   # raw source prefix -> folder
    synced_skill_prefix: str = "anthropic-skills"            # observed, not documented
    narrative: Path = field(default_factory=lambda: config_dir() / "erzaehlung.html")
    artifact_url: str | None = None
    title: str = "Skill-Landkarte"
    refresh_hint: str = "skill-map build && skill-map mark-published"                    # how to refresh, named in the hook line and on the page
    runbook_text: bool = False                               # show a runbook's file too, not only its front matter
    profiles: dict[str, dict] = field(default_factory=dict)  # name -> overrides, checked by load_config
    profile: str | None = None                               # the profile this config was loaded for


DEFAULT_HINT = Config.refresh_hint
PROFILE_KEYS = ("title", "artifact_url", "refresh_hint", "release_text", "runbook_text")
PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")      # becomes a folder name


def default_path() -> Path:
    return config_dir() / "skill-map.conf"


def _str(data: dict, key: str, where: Path) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return value


def _bool(data: dict, key: str, where: Path) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: {key} must be true or false")
    return value


def _str_list(data: dict, key: str, where: Path) -> list[str]:
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: {key} must be a list of strings")
    return value


def _str_table(data: dict, key: str, where: Path) -> dict[str, str]:
    value = data[key]
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise ConfigError(f"{where}: {key} must be a table of strings")
    return dict(value)


def _profiles(data: dict, cfg: Config, where: Path) -> dict[str, dict]:
    """Check [profiles.<name>]: known keys and types only, and release_text may name only
    keys that withhold_text holds back - it never lifts any other rule."""
    value = data["profiles"]
    if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
        raise ConfigError(f"{where}: profiles must be [profiles.<name>] tables")
    profiles = {}
    for name, table in value.items():
        at = f"profiles.{name}"
        if not PROFILE_NAME.fullmatch(name):
            raise ConfigError(f"{where}: profile name {name} must be lower case letters, digits, - or _")
        for key in table:
            if key not in PROFILE_KEYS:
                raise ConfigError(f"{where}: {at}: unknown key {key} (allowed: {', '.join(PROFILE_KEYS)})")
        for key in ("title", "artifact_url", "refresh_hint"):
            if key in table:
                _str(table, key, where)
        if "runbook_text" in table:
            _bool(table, "runbook_text", Path(f"{where}: {at}"))
        if "release_text" in table:
            for key in _str_list(table, "release_text", Path(f"{where}: {at}")):
                if key not in cfg.withhold_text:
                    raise ConfigError(f"{where}: {at}: release_text names {key}, which withhold_text does not hold back")
        profiles[name] = dict(table)
    return profiles


def _apply_profile(cfg: Config, name: str, where: Path) -> Config:
    if name not in cfg.profiles:
        known = ", ".join(sorted(cfg.profiles)) or "none"
        raise ConfigError(f"{where}: unknown profile {name} (defined: {known})")
    table = cfg.profiles[name]
    released = set(table.get("release_text", []))
    hint = cfg.refresh_hint
    if hint == DEFAULT_HINT:        # the default names the plain commands; a profile needs its own
        hint = f"skill-map --profile {name} build && skill-map --profile {name} mark-published"
    return replace(cfg, profile=name,
                   title=table.get("title", cfg.title),
                   artifact_url=table.get("artifact_url", cfg.artifact_url),
                   refresh_hint=table.get("refresh_hint", hint),
                   runbook_text=table.get("runbook_text", cfg.runbook_text),
                   withhold_text={k: v for k, v in cfg.withhold_text.items() if k not in released})


def load_config(path: Path | None = None, profile: str | None = None) -> Config:
    """Read the config file; a missing file gives the defaults. With a profile, its
    overrides are applied on top of the rest of the file."""
    where = path or default_path()
    if not where.is_file():
        return _apply_profile(Config(), profile, where) if profile is not None else Config()
    try:
        data = tomllib.loads(where.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"{where}: invalid TOML ({e})") from e

    cfg = Config()
    for key in data:
        if key not in Config.__dataclass_fields__:
            raise ConfigError(f"{where}: unknown key {key}")
    if "vault" in data:
        cfg.vault = expand(_str(data, "vault", where))
    if "title" in data:
        cfg.title = _str(data, "title", where)
    if "refresh_hint" in data:
        cfg.refresh_hint = _str(data, "refresh_hint", where)
    if "runbook_text" in data:
        cfg.runbook_text = _bool(data, "runbook_text", where)
    if "synced_skill_prefix" in data:
        cfg.synced_skill_prefix = _str(data, "synced_skill_prefix", where)
    if "artifact_url" in data:
        cfg.artifact_url = _str(data, "artifact_url", where)
    if "narrative" in data:
        cfg.narrative = expand(_str(data, "narrative", where))
    if "tools" in data:
        cfg.tools = [str(expand(t)) for t in _str_list(data, "tools", where)]   # folder globs
    if "hide" in data:
        cfg.hide = _str_list(data, "hide", where)
    if "source_roots" in data:
        cfg.source_roots = [expand(r) for r in _str_list(data, "source_roots", where)]
    if "builtins" in data:
        cfg.builtins = _str_table(data, "builtins", where)
    if "source_prefixes" in data:
        cfg.source_prefixes = {k: expand(v) for k, v in _str_table(data, "source_prefixes", where).items()}
    if "areas" in data:
        cfg.areas = _str_table(data, "areas", where)
    if "withhold_text" in data:
        value = data["withhold_text"]
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            cfg.withhold_text = {k: None for k in value}
        elif isinstance(value, dict):
            cfg.withhold_text = _str_table(data, "withhold_text", where)
        else:
            raise ConfigError(f"{where}: withhold_text must be a list of keys or a table key = reason")
    if "projects" in data:
        value = data["projects"]
        if not isinstance(value, list) or not all(
                isinstance(p, dict) and isinstance(p.get("path"), str) and isinstance(p.get("label"), str)
                for p in value):
            raise ConfigError(f"{where}: projects must be [[projects]] tables with path and label")
        cfg.projects = [Project(expand(p["path"]), p["label"]) for p in value]
    if "profiles" in data:
        cfg.profiles = _profiles(data, cfg, where)
    if profile is not None:
        return _apply_profile(cfg, profile, where)
    return cfg
