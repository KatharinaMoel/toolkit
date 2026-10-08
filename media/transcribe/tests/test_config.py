import os
from pathlib import Path

import pytest

from transcribe import config


def test_defaults_without_file(tmp_path):
    cfg = config.load(tmp_path / "missing", env={"HOME": str(tmp_path)})
    assert cfg.model == "small"
    assert cfg.language == "en"
    assert cfg.keep_audio is False
    assert cfg.cpu_threads == (os.cpu_count() or 4)
    assert cfg.state_file == Path(tmp_path, ".local/state/transcribe/queue.json")


def test_parse_values_comments_quotes_and_tilde(tmp_path):
    f = tmp_path / "config"
    f.write_text(
        "# comment\n\nOUT_DIR=~/transcripts\nCACHE_DIR=\"/var/tmp/tc\"\nMODEL='medium'\n"
        "LANGUAGE=auto\nCPU_THREADS=8\nKEEP_AUDIO=yes\nSTATE_FILE=/s/q.json  # trailing\n")
    cfg = config.load(f, env={"HOME": "/home/u"})
    assert cfg.out_dir == Path("/home/u/transcripts")
    assert cfg.cache_dir == Path("/var/tmp/tc")
    assert (cfg.model, cfg.language, cfg.cpu_threads, cfg.keep_audio) == ("medium", "auto", 8, True)
    assert cfg.state_file == Path("/s/q.json")


def test_no_shell_evaluation(tmp_path):
    f = tmp_path / "config"
    f.write_text("OUT_DIR=$(touch pwned)/x\n")
    cfg = config.load(f, env={"HOME": "/h"})
    assert str(cfg.out_dir) == "$(touch pwned)/x"
    assert not Path("pwned").exists()


@pytest.mark.parametrize("line", ["UNKNOWN=1", "CPU_THREADS=many", "CPU_THREADS=0",
                                  "KEEP_AUDIO=maybe", "just text", "LANGUAGE="])
def test_bad_lines_are_refused(tmp_path, line):
    f = tmp_path / "config"
    f.write_text(line + "\n")
    with pytest.raises(config.ConfigError):
        config.load(f, env={"HOME": "/h"})


def test_env_points_to_config(tmp_path):
    f = tmp_path / "c"
    f.write_text("MODEL=tiny\n")
    assert config.default_path({"TRANSCRIBE_CONFIG": str(f), "HOME": "/h"}) == f
    assert config.default_path({"HOME": "/h"}) == Path("/h/.config/transcribe/config")


def test_example_conf_parses():
    example = Path(__file__).resolve().parent.parent / "example.conf"
    assert example.is_file()
    values = config.parse(example.read_text())
    assert set(values) == set(config.KEYS)
    cfg = config.load(example, env={"HOME": "/h"})
    assert cfg.source == example and cfg.model == "small" and cfg.keep_audio is False
    assert str(cfg.out_dir).startswith("/h/")
