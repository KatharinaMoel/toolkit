import os
import subprocess

from conftest import LAUNCHER
from skill_map.cli import main


def test_help_exits_0(capsys):
    assert main(["--help"]) == 0
    assert "skill-map build" in capsys.readouterr().out


def test_unknown_subcommand_exits_2(home, capsys):
    assert main(["frobnicate"]) == 2
    assert "usage" in capsys.readouterr().err


def test_invalid_toml_exits_2_naming_the_path(home, conf, capsys):
    path = conf("vault = [unclosed")
    assert main(["fingerprint"]) == 2
    assert str(path) in capsys.readouterr().err


def test_wrong_type_in_config_exits_2(home, conf, capsys):
    conf("withhold_text = 3")
    assert main(["fingerprint"]) == 2
    assert "withhold_text" in capsys.readouterr().err


def test_launcher_works_through_a_symlink(home, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "skill-map").symlink_to(LAUNCHER)
    env = dict(os.environ)
    out = subprocess.run([str(bindir / "skill-map"), "--help"], capture_output=True, text=True,
                         env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "skill-map build" in out.stdout
