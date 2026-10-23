import os
import subprocess

import pytest
from conftest import LAUNCHER, mr

from mr_export import cli
from mr_export.cli import main


def test_help_exits_0(capsys):
    assert main(["--help"]) == 0
    assert "mr-export fetch" in capsys.readouterr().out


def test_no_subcommand_exits_2(home, capsys):
    assert main([]) == 2


def test_unknown_state_exits_2(home, capsys):
    assert main(["fetch", "--state", "draft"]) == 2


def test_wrong_type_in_config_exits_2_naming_the_key(home, capsys):
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True)
    (conf / "mr-export.conf").write_text("images = 'yes'\n")
    assert main(["fetch", "--yes"]) == 2
    assert "images" in capsys.readouterr().err


@pytest.fixture
def fake(monkeypatch, gitlab, home):
    """Every Runner in the CLI talks to the fake instead of real git and glab."""
    orig = cli.Runner.__init__

    def init(self, repo, console, run=None, timeout=180):
        orig(self, repo, console, run=gitlab, timeout=timeout)
    monkeypatch.setattr(cli.Runner, "__init__", init)
    gitlab.repo = str(home / "app")
    return gitlab


def test_fetch_without_terminal_asks_for_yes_and_reads_nothing(fake, home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["fetch"]) == 1
    err = capsys.readouterr().err
    assert "--yes" in err and "Nothing was read" in err
    assert not any(c[0] == "glab" for c in fake.calls)
    assert not (home / "mr-export").exists()


def test_fetch_answering_no_stops(fake, home, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert main(["fetch"]) == 1
    assert not any(c[0] == "glab" for c in fake.calls)


def test_fetch_yes_writes_snapshot_and_overview(fake, home, capsys):
    assert main(["fetch", "--yes"]) == 0
    out, err = capsys.readouterr()
    index = out.strip()
    assert index.startswith(str(home / "mr-export" / "app")) and index.endswith("index.html")
    assert os.path.isfile(index)
    assert "read only" in err and "From:" in err and "To:" in err   # header before the first read


def test_config_out_dir_is_used(fake, home, capsys):
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True)
    (conf / "mr-export.conf").write_text(f'out_dir = "{home}/elsewhere"\nimages = false\n')
    assert main(["fetch", "--yes"]) == 0
    assert capsys.readouterr().out.startswith(str(home / "elsewhere" / "app"))
    assert not any("uploads" in c[-1] for c in fake.calls)


def test_render_without_folder_takes_the_newest_snapshot(fake, home, capsys):
    main(["fetch", "--yes"])
    capsys.readouterr()
    assert main(["render"]) == 0
    assert capsys.readouterr().out.strip().endswith("index.html")


def test_render_without_any_snapshot_says_what_to_do(fake, home, capsys):
    assert main(["render"]) == 1
    assert "mr-export fetch" in capsys.readouterr().err


def test_launcher_works_through_a_symlink(home, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "mr-export").symlink_to(LAUNCHER)
    out = subprocess.run([str(bindir / "mr-export"), "--help"], capture_output=True, text=True,
                         env=dict(os.environ), timeout=30)
    assert out.returncode == 0, out.stderr
    assert "mr-export fetch" in out.stdout


def test_render_cli_on_a_folder(home, tmp_path, capsys):
    import json
    (tmp_path / "mrs-list.ndjson").write_text(json.dumps(mr(3)) + "\n")
    assert main(["render", str(tmp_path)]) == 0
    assert (tmp_path / "mr" / "3.html").is_file()
