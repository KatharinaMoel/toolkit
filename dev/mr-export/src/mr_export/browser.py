"""Opening the overview in a browser. A browser installed as a Flatpak only sees
folders it was granted; given a single file through the document portal, it shows
that file but every link next to it breaks. Detect that and say how to fix it."""
import os
import shlex
from pathlib import Path

from .runner import CommandError, Runner

ALL_FILES = {"host", "host-os", "home"}


def _granted(entry: str) -> Path | None:
    path = entry.rsplit(":", 1)[0] if entry.endswith((":ro", ":rw", ":create")) else entry
    if path.startswith("~/"):
        return Path.home() / path[2:]
    return Path(path) if path.startswith("/") else None


def flatpak_without_access(runner: Runner, path: Path) -> str | None:
    """The Flatpak app id of the default HTML browser when it cannot read `path`'s folder."""
    try:
        desktop = runner.tool(["xdg-mime", "query", "default", "text/html"],
                              "Ask which browser opens HTML files")
    except CommandError:
        return None
    app = desktop.removesuffix(".desktop")
    if not app or not runner.tool_ok(["flatpak", "info", app], None):
        return None
    try:
        perms = runner.tool(["flatpak", "info", "--show-permissions", app],
                            "That browser is a Flatpak: read which folders it may open")
    except CommandError:
        return None
    entries = []
    for line in perms.splitlines():
        if line.startswith("filesystems="):
            entries = [e for e in line.split("=", 1)[1].split(";") if e]
    if ALL_FILES & {e.split(":")[0] for e in entries}:
        return None
    target = Path(os.path.abspath(path))
    for e in entries:
        granted = _granted(e)
        if granted and (target == granted or granted in target.parents):
            return None
    return app


def override_command(app: str, folder: str | Path) -> str:
    return f"flatpak override --user --filesystem={shlex.quote(str(folder))}:ro {app}"


def open_page(runner: Runner, path: Path) -> None:
    runner.tool(["xdg-open", str(path)], "Open the overview in your default browser")
