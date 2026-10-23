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


def test_fetch_while_locked_says_so(fake, home, capsys):
    import fcntl
    root = home / "mr-export" / "app"
    root.mkdir(parents=True)
    with open(root / ".fetch.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main(["fetch", "--yes"]) == 1
    assert "another mr-export fetch is running" in capsys.readouterr().err


def test_fetch_uses_repo_table_of_config(fake, home, no_git_state):
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True)
    (conf / "mr-export.conf").write_text('[repo."app"]\nemergency_branches = { dev = "hotfix/dev" }\n')
    assert main(["fetch", "--yes"]) == 0
    assert no_git_state[0]["emergency"] == {"dev": "hotfix/dev"}


def test_fetch_sets_latest_and_prunes(fake, home, capsys):
    import json as _json
    root = home / "mr-export" / "app"
    for i in range(1, 4):
        p = root / f"2026-01-0{i}_0900"
        (p / "mr").mkdir(parents=True)
        (p / "mrs.ndjson").write_text("")
        (p / "meta.json").write_text(_json.dumps({"complete": True}))
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True)
    (conf / "mr-export.conf").write_text("keep = 2\n")
    assert main(["fetch", "--yes"]) == 0
    err = capsys.readouterr().err
    assert (root / "latest").is_symlink()
    assert (root / "latest" / "index.html").is_file()
    assert sorted(p.name for p in root.iterdir() if p.name.startswith("2026-01"))  == ["2026-01-03_0900"]
    assert "Keep the newest 2 snapshots" in err and "2026-01-01_0900" in err


def test_render_without_folder_uses_latest(fake, home, capsys):
    main(["fetch", "--yes"])
    capsys.readouterr()
    (home / "mr-export" / "app" / "2099-01-01_0000").mkdir()   # newer, but not a finished snapshot
    assert main(["render"]) == 0
    out, err = capsys.readouterr()
    assert "latest -> 20" in err and "2099" not in out


def test_config_ordering_and_age_reach_the_page(fake, home, capsys):
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True)
    (conf / "mr-export.conf").write_text('stale_after_hours = 7\n[repo."app"]\ntop_labels = ["Review: easy"]\n')
    assert main(["fetch", "--yes"]) == 0
    index = capsys.readouterr().out.strip()
    html = open(index).read()
    assert 'data-stale-hours="7"' in html
    assert main(["render", str(home / "mr-export" / "app" / "latest")]) == 0
    assert 'data-stale-hours="7"' in open(index).read()


def test_open_warns_about_flatpak_and_still_opens(fake, home, capsys, monkeypatch):
    from mr_export import browser
    main(["fetch", "--yes"])
    capsys.readouterr()
    opened = []
    monkeypatch.setattr(browser, "flatpak_without_access", lambda runner, path: "com.google.Chrome")
    monkeypatch.setattr(browser, "open_page", lambda runner, path: opened.append(path))
    assert main(["open"]) == 0
    err = capsys.readouterr().err
    assert "flatpak override --user --filesystem=" in err and "com.google.Chrome" in err
    assert opened and str(opened[0]).endswith("latest/index.html")


def test_open_without_snapshot_says_what_to_do(fake, home, capsys):
    assert main(["open"]) == 1
    assert "mr-export fetch" in capsys.readouterr().err


def test_quiet_fetch_prints_nothing_on_success(fake, home, capsys):
    assert main(["fetch", "--yes", "--quiet"]) == 0
    out, err = capsys.readouterr()
    assert err == "" and out.strip().endswith("index.html")
