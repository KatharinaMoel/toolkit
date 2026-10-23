import re
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from mr_export import schedule
from mr_export.runner import Console, Runner


class FakeSystemd:
    """Answers systemctl/journalctl/git and records every call."""

    def __init__(self, env="SSH_AUTH_SOCK=/run/user/1000/keyring/ssh\nHOME=/home/u\n"):
        self.env = env
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd=None, capture_output=True, timeout=None):
        self.calls.append(list(cmd))
        out = ""
        if cmd[:3] == ["systemctl", "--user", "show-environment"]:
            out = self.env
        elif cmd[:2] == ["systemctl", "--user"] and "list-timers" in cmd:
            out = "NEXT LEFT LAST PASSED UNIT\n"
        elif cmd[0] == "journalctl":
            out = "Oct 23 12:00 mr-export[1]: ok\n"
        return subprocess.CompletedProcess(cmd, 0, out.encode(), b"")


@pytest.fixture
def sysd(home):
    return FakeSystemd()


def make_runner(fake, repo):
    return Runner(repo, Console(StringIO()), run=fake)


def test_unit_files_content(tmp_path):
    launcher, repo = Path("/opt/tools/mr-export"), Path("/work/Garden Planner")
    files = schedule.unit_files(launcher, repo, "1h")
    name = schedule.unit_name(repo)
    service, timer = files[f"{name}.service"], files[f"{name}.timer"]
    assert "Type=oneshot" in service
    assert 'ExecStart="/opt/tools/mr-export" fetch --yes --quiet --repo "/work/Garden Planner"' in service
    assert "OnUnitActiveSec=1h" in timer and "OnBootSec=5min" in timer
    assert "WantedBy=timers.target" in timer and f"Unit={name}.service" in timer


def test_percent_in_paths_is_escaped_for_systemd():
    files = schedule.unit_files(Path("/opt/mr-export"), Path("/work/100%"), "1h")
    service = next(v for k, v in files.items() if k.endswith(".service"))
    assert '"/work/100%%"' in service


def test_unit_name_is_escaped():
    a = schedule.unit_name(Path("/work/Garden Planner"))
    b = schedule.unit_name(Path("/work/Übung"))
    c = schedule.unit_name(Path("/work/Öbung"))
    for n in (a, b, c):
        assert re.fullmatch(r"mr-export-[A-Za-z0-9:_.\-]+", n), n
    assert len({a, b, c}) == 3


@pytest.mark.parametrize("ok", ["30min", "1h", "2h"])
def test_parse_every_accepts(ok):
    assert schedule.parse_every(ok) == ok


@pytest.mark.parametrize("bad", ["0h", "5s", "1d", "", "h", "1 h"])
def test_parse_every_refuses(bad):
    with pytest.raises(ValueError):
        schedule.parse_every(bad)


def test_install_writes_units_then_enables(sysd, home, tmp_path):
    repo = tmp_path / "app"
    name = schedule.install(make_runner(sysd, repo), Console(StringIO()), Path("/opt/mr-export"), repo, "1h")
    unit_dir = home / ".config" / "systemd" / "user"
    assert (unit_dir / f"{name}.service").is_file() and (unit_dir / f"{name}.timer").is_file()
    calls = [c for c in sysd.calls if c[0] == "systemctl"]
    assert calls[-2:] == [["systemctl", "--user", "daemon-reload"],
                          ["systemctl", "--user", "enable", "--now", f"{name}.timer"]]


def test_install_warns_without_ssh_agent(home, tmp_path):
    fake, err = FakeSystemd(env="HOME=/home/u\n"), StringIO()
    schedule.install(make_runner(fake, tmp_path), Console(err), Path("/opt/mr-export"), tmp_path, "1h")
    assert "systemctl --user import-environment SSH_AUTH_SOCK" in err.getvalue()


def test_off_disables_and_removes(sysd, home, tmp_path):
    repo = tmp_path / "app"
    name = schedule.install(make_runner(sysd, repo), Console(StringIO()), Path("/opt/mr-export"), repo, "1h")
    schedule.remove(make_runner(sysd, repo), Console(StringIO()), repo)
    unit_dir = home / ".config" / "systemd" / "user"
    assert not (unit_dir / f"{name}.timer").exists() and not (unit_dir / f"{name}.service").exists()
    assert ["systemctl", "--user", "disable", "--now", f"{name}.timer"] in sysd.calls


def test_status_shows_timer_and_last_runs(sysd, tmp_path):
    repo = tmp_path / "app"
    name = schedule.unit_name(repo)
    schedule.status(make_runner(sysd, repo), Console(StringIO()), repo)
    assert ["systemctl", "--user", "list-timers", f"{name}.timer", "--all", "--no-pager"] in sysd.calls
    assert ["journalctl", "--user", "-u", f"{name}.service", "-n", "20", "--no-pager"] in sysd.calls


def test_cli_schedule_without_terminal_writes_nothing(home, tmp_path, monkeypatch, capsys):
    from mr_export import cli
    fake = FakeSystemd()
    orig = cli.Runner.__init__
    monkeypatch.setattr(cli.Runner, "__init__",
                        lambda self, repo, console, run=None, timeout=180: orig(self, repo, console, run=fake))
    monkeypatch.setattr(cli, "repo_root", lambda runner: tmp_path / "app")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["schedule", "--every", "1h"]) == 1
    assert not (home / ".config" / "systemd").exists()
    assert "--yes" in capsys.readouterr().err
