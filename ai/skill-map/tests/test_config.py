from pathlib import Path

import pytest

from skill_map.config import ConfigError, load_config
from skill_map.paths import claude_home, state_dir, tilde


def test_no_config_file_gives_the_defaults(home):
    cfg = load_config()
    assert cfg.vault is None
    assert cfg.projects == []
    assert cfg.tools == []
    assert cfg.builtins == {}
    assert cfg.withhold_text == {}
    assert cfg.hide == []
    assert cfg.title == "Skill-Landkarte"
    assert cfg.synced_skill_prefix == "anthropic-skills"
    assert cfg.artifact_url is None
    assert cfg.narrative == home / ".config" / "skill-map" / "erzaehlung.html"


def test_values_are_read_and_paths_expanded(home, conf):
    conf('''
vault = "~/notes"
title = "Meine Karte"
source_roots = ["~/notes", "/opt/kios/templates"]
tools = ["~/src/toolkit/*/*/"]
hide = ["agent:*"]
withhold_text = ["timesheet"]
artifact_url = "https://example.invalid/a"
[[projects]]
path = "~/projects/app"
label = "App-Repo"
[builtins]
code-review = "Review des aktuellen Diffs"
[areas]
arbeit = "Arbeit"
''')
    cfg = load_config()
    assert cfg.vault == home / "notes"
    assert cfg.title == "Meine Karte"
    assert cfg.source_roots == [home / "notes", Path("/opt/kios/templates")]
    assert cfg.tools == [str(home / "src/toolkit/*/*")]
    assert cfg.projects[0].path == home / "projects/app" and cfg.projects[0].label == "App-Repo"
    assert cfg.builtins == {"code-review": "Review des aktuellen Diffs"}
    assert cfg.areas == {"arbeit": "Arbeit"}
    assert cfg.withhold_text == {"timesheet": None}
    assert cfg.hide == ["agent:*"]


def test_withhold_text_as_table_keeps_the_reason(home, conf):
    conf('[withhold_text]\ntimesheet = "Zeitkonto"\n')
    assert load_config().withhold_text == {"timesheet": "Zeitkonto"}


@pytest.mark.parametrize("text, key", [
    ("vault = 3", "vault"),
    ("projects = [\"x\"]", "projects"),
    ("[[projects]]\nlabel = \"no path\"", "projects"),
    ("tools = \"one\"", "tools"),
    ("[builtins]\nx = 1", "builtins"),
    ("hide = [1]", "hide"),
    ("unknown_key = 1", "unknown_key"),
])
def test_wrong_types_are_config_errors(home, conf, text, key):
    conf(text)
    with pytest.raises(ConfigError, match=key):
        load_config()


def test_claude_config_dir_moves_claude_home(home, monkeypatch, tmp_path):
    assert claude_home() == home / ".claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    assert claude_home() == tmp_path / "cc"


def test_state_dir_follows_xdg(home):
    assert state_dir() == home / ".local" / "state" / "skill-map"


def test_tilde_replaces_home_and_account_ids(home):
    assert tilde(home / "x" / "y.md") == "~/x/y.md"
    pair = "00000000-1111-4222-8333-444444444444_55555555-6666-4777-8888-999999999999"
    assert tilde(home / ".claude" / "skills" / "synced" / pair / "pdf") == "~/.claude/skills/synced/<konto>/pdf"
    assert tilde("/opt/a") == "/opt/a"
