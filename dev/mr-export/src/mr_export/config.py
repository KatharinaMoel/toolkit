"""The optional config file (TOML). Every key is optional."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

STATES = ("opened", "merged", "closed", "locked", "all")


class ConfigError(Exception):
    """Invalid TOML or a key with the wrong type; the message names the file and key."""


@dataclass
class Config:
    out_dir: Path            # snapshots go to <out_dir>/<repo name>/<timestamp>/
    state: str = "opened"    # which merge requests to read
    images: bool = True      # download images uploaded to descriptions and comments


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mr-export"


def default_path() -> Path:
    return config_dir() / "mr-export.conf"


def load_config(path: Path | None = None) -> tuple[Config, Path | None]:
    """Returns the config and the file it came from (None when there is no file)."""
    path = path or default_path()
    cfg = Config(out_dir=Path.home() / "mr-export")
    if not path.is_file():
        return cfg, None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    unknown = sorted(set(data) - {"out_dir", "state", "images"})
    if unknown:
        raise ConfigError(f"{path}: unknown key(s): {', '.join(unknown)}")
    if "out_dir" in data:
        if not isinstance(data["out_dir"], str) or not data["out_dir"]:
            raise ConfigError(f"{path}: out_dir must be a non-empty string")
        cfg.out_dir = Path(os.path.expanduser(data["out_dir"]))
    if "state" in data:
        if data["state"] not in STATES:
            raise ConfigError(f"{path}: state must be one of {', '.join(STATES)}")
        cfg.state = data["state"]
    if "images" in data:
        if not isinstance(data["images"], bool):
            raise ConfigError(f"{path}: images must be true or false")
        cfg.images = data["images"]
    return cfg, path
