import pytest

from mr_export.config import ConfigError, load_config


def write(home, text):
    conf = home / ".config" / "mr-export"
    conf.mkdir(parents=True, exist_ok=True)
    path = conf / "mr-export.conf"
    path.write_text(text)
    return path


def test_defaults_without_file(home):
    cfg, path = load_config()
    assert path is None
    assert cfg.keep == 15
    assert cfg.top_labels == ["Approval ready"]
    assert cfg.emergency_branches == {"dev": "notfall/dev", "main": "notfall/main"}
    assert cfg.stale_after_hours == 3


def test_v1_file_still_loads(home):
    write(home, 'out_dir = "~/elsewhere"\nstate = "all"\nimages = false\n')
    cfg, _ = load_config()
    assert cfg.out_dir == home / "elsewhere" and cfg.state == "all" and cfg.images is False
    assert cfg.keep == 15


def test_repo_table_overrides_global(home):
    write(home, 'keep = 10\n[repo."Garden Planner"]\nkeep = 5\ntop_labels = ["Urgent"]\n')
    assert load_config(repo="Garden Planner")[0].keep == 5
    assert load_config(repo="Garden Planner")[0].top_labels == ["Urgent"]
    assert load_config(repo="other")[0].keep == 10
    assert load_config()[0].keep == 10


@pytest.mark.parametrize("text, key", [
    ('keep = "x"', "keep"),
    ("keep = 0", "keep"),
    ('top_labels = "a"', "top_labels"),
    ("emergency_branches = { dev = 1 }", "emergency_branches"),
    ("stale_after_hours = 0", "stale_after_hours"),
])
def test_wrong_types_name_the_key(home, text, key):
    write(home, text + "\n")
    with pytest.raises(ConfigError, match=key):
        load_config()


def test_unknown_key_in_repo_table_is_an_error(home):
    write(home, '[repo."app"]\nkep = 3\n')
    with pytest.raises(ConfigError, match=r'repo\."app".*kep'):
        load_config(repo="app")
