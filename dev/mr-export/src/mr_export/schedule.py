"""A systemd user timer that runs `mr-export fetch --yes --quiet` for one repository.
It runs only while the user is logged in, so glab's keyring and the session's SSH
agent are there; problems end up in the journal (`schedule --status`)."""
import hashlib
import os
import re
from pathlib import Path

from .runner import CommandError, Console, Runner

EVERY = re.compile(r"([1-9]\d*)(min|h)")


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def unit_name(repo: Path) -> str:
    """mr-export-<folder name in safe characters>-<short hash of the full path>, so
    names stay valid and two repositories never share a unit."""
    slug = re.sub(r"[^A-Za-z0-9_.]+", "_", repo.name).strip("_") or "repo"
    digest = hashlib.sha256(str(repo).encode()).hexdigest()[:6]
    return f"mr-export-{slug}-{digest}"


def parse_every(text: str) -> str:
    if not EVERY.fullmatch(text):
        raise ValueError(f"'{text}' is not an interval like 30min, 1h or 2h")
    return text


def _quote(path: Path) -> str:
    """A path as one argument in a systemd unit: double quotes, and % doubled
    because systemd reads %x as a placeholder."""
    text = str(path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{text}"'


def unit_files(launcher: Path, repo: Path, every: str) -> dict[str, str]:
    name = unit_name(repo)
    service = (
        "[Unit]\n"
        f"Description=mr-export: read the merge requests of {repo.name}\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={_quote(launcher)} fetch --yes --quiet --repo {_quote(repo)}\n")
    timer = (
        "[Unit]\n"
        f"Description=mr-export every {every} for {repo.name}\n\n"
        "[Timer]\n"
        "OnBootSec=5min\n"
        f"OnUnitActiveSec={every}\n"
        "RandomizedDelaySec=2min\n"
        f"Unit={name}.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n")
    return {f"{name}.service": service, f"{name}.timer": timer}


def ssh_agent_visible(runner: Runner) -> bool:
    try:
        env = runner.tool(["systemctl", "--user", "show-environment"],
                          "Check that timer runs can reach your SSH agent")
    except CommandError:
        return False
    return any(line.startswith("SSH_AUTH_SOCK=") for line in env.splitlines())


def install(runner: Runner, console: Console, launcher: Path, repo: Path, every: str) -> str:
    """Writes both units and enables the timer; returns the unit name."""
    if not ssh_agent_visible(runner):
        console.note("Timer runs cannot see your SSH agent, so Git over SSH would fail in them.")
        console.note("Fix once per login session: systemctl --user import-environment SSH_AUTH_SOCK")
    target = unit_dir()
    target.mkdir(parents=True, exist_ok=True)
    files = unit_files(launcher, repo, every)
    console.step(f"Write {len(files)} unit files to {target}")
    for fname, content in files.items():
        (target / fname).write_text(content, encoding="utf-8")
        console.result(str(target / fname))
    name = unit_name(repo)
    runner.tool(["systemctl", "--user", "daemon-reload"], "Let systemd read the new units")
    runner.tool(["systemctl", "--user", "enable", "--now", f"{name}.timer"],
                "Start the timer now and with every login")
    return name


def remove(runner: Runner, console: Console, repo: Path) -> None:
    name = unit_name(repo)
    runner.tool(["systemctl", "--user", "disable", "--now", f"{name}.timer"], "Stop and disable the timer")
    for fname in (f"{name}.timer", f"{name}.service"):
        path = unit_dir() / fname
        if path.exists():
            path.unlink()
            console.result(f"removed {path}")
    runner.tool(["systemctl", "--user", "daemon-reload"], "Let systemd forget the removed units")


def status(runner: Runner, console: Console, repo: Path) -> str:
    name = unit_name(repo)
    timers = runner.tool(["systemctl", "--user", "list-timers", f"{name}.timer", "--all", "--no-pager"],
                         "When the timer runs next and ran last")
    log = runner.tool(["journalctl", "--user", "-u", f"{name}.service", "-n", "20", "--no-pager"],
                      "The last runs and their messages")
    return f"{timers}\n\n{log}"
