"""The optional config file (TOML). Every key is optional: without a file the tool
shows Claude Code's own places. Personal sources are switched on here."""
import tomllib
from dataclasses import dataclass, field
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
    synced_skill_prefix: str = "anthropic-skills"            # observed, not documented
    narrative: Path = field(default_factory=lambda: config_dir() / "erzaehlung.html")
    artifact_url: str | None = None
    title: str = "Skill-Landkarte"


def default_path() -> Path:
    return config_dir() / "skill-map.conf"


def _str(data: dict, key: str, where: Path) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
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


def load_config(path: Path | None = None) -> Config:
    """Read the config file; a missing file gives the defaults."""
    where = path or default_path()
    if not where.is_file():
        return Config()
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
    return cfg
