"""The optional config file (TOML). Every key is optional. Global keys at the top,
per-repository overrides in [repo."<clone folder name>"] tables."""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STATES = ("opened", "merged", "closed", "locked", "all")


class ConfigError(Exception):
    """Invalid TOML or a key with the wrong type; the message names the file and key."""


@dataclass
class Config:
    out_dir: Path            # snapshots go to <out_dir>/<repo name>/<timestamp>/
    state: str = "opened"    # which merge requests to read
    images: bool = True      # download files uploaded to descriptions and comments
    keep: int = 15           # newest snapshots kept by retention
    top_labels: list[str] = field(default_factory=lambda: ["Approval ready"])   # sorted to the top
    emergency_branches: dict[str, str] = field(
        default_factory=lambda: {"dev": "notfall/dev", "main": "notfall/main"})  # base -> emergency branch
    stale_after_hours: int = 3   # the overview marks a snapshot as old after this many hours


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mr-export"


def default_path() -> Path:
    return config_dir() / "mr-export.conf"


def _out_dir(v):
    if not isinstance(v, str) or not v:
        raise ValueError("must be a non-empty string")
    return Path(os.path.expanduser(v))


def _state(v):
    if v not in STATES:
        raise ValueError(f"must be one of {', '.join(STATES)}")
    return v


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("must be true or false")
    return v


def _positive_int(v):
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ValueError("must be a whole number of at least 1")
    return v


def _str_list(v):
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ValueError('must be a list of strings, e.g. ["Approval ready"]')
    return v


def _str_map(v):
    if not isinstance(v, dict) or not all(isinstance(k, str) and isinstance(x, str) and x for k, x in v.items()):
        raise ValueError('must map branch names to branch names, e.g. { dev = "notfall/dev" }')
    return v


KEYS = {
    "out_dir": _out_dir, "state": _state, "images": _bool, "keep": _positive_int,
    "top_labels": _str_list, "emergency_branches": _str_map, "stale_after_hours": _positive_int,
}


def _apply(cfg: Config, data: dict, where: str) -> None:
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")
    for key, check in KEYS.items():
        if key in data:
            try:
                setattr(cfg, key, check(data[key]))
            except ValueError as e:
                raise ConfigError(f"{where}: {key} {e}") from None


def load_config(path: Path | None = None, repo: str | None = None) -> tuple[Config, Path | None]:
    """Returns the config and the file it came from (None when there is no file).
    With `repo`, keys of [repo."<repo>"] override the global ones."""
    path = path or default_path()
    cfg = Config(out_dir=Path.home() / "mr-export")
    if not path.is_file():
        return cfg, None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    tables = data.pop("repo", {})
    if not isinstance(tables, dict):
        raise ConfigError(f'{path}: repo must hold tables like [repo."name"]')
    _apply(cfg, data, str(path))
    if repo is not None and repo in tables:
        if not isinstance(tables[repo], dict):
            raise ConfigError(f'{path}: repo."{repo}" must be a table')
        _apply(cfg, tables[repo], f'{path} [repo."{repo}"]')
    return cfg, path
