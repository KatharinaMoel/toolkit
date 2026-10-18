"""Where things live: Claude Code's folder, the tool's config and state, and how
paths are written into the output (home as ~, account ids as <konto>)."""
import os
import re
from pathlib import Path

# An account id, or a pair of them joined by "_" (folder names under synced/).
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f-]{27}(_[0-9a-f]{8}-[0-9a-f-]{27})?", re.IGNORECASE)


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def claude_home() -> Path:
    """$CLAUDE_CONFIG_DIR when set, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or home() / ".claude")


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config") / "skill-map"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or home() / ".local" / "state") / "skill-map"


def expand(value: str) -> Path:
    """A path from the config: ~ means $HOME."""
    if value == "~" or value.startswith("~/"):
        return home() / value[2:]
    return Path(value)


def tilde(path: Path | str) -> str:
    """A path as written into the output: $HOME as ~, account ids as <konto>."""
    text = str(path)
    h = str(home())
    if text == h:
        text = "~"
    elif text.startswith(h + "/"):
        text = "~" + text[len(h):]
    return UUID_RE.sub("<konto>", text)
