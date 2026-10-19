"""Profiles: a second page from the same config, with its own title, address, state
and a few texts released from withhold_text - never from a classification."""
import json

import pytest

from skill_map.cli import main
from skill_map.config import ConfigError, load_config
from skill_map.paths import state_dir
from world import CONFIG

TEAM = CONFIG.replace('withhold_text = ["zeit"]', 'withhold_text = ["zeit", "plain"]') + """
[profiles.team]
title = "Karte (Team)"
artifact_url = "https://example.invalid/team"
release_text = ["plain"]
"""


def state(home):
    return home / ".local/state/skill-map"


def built(home, profile=None):
    folder = state(home) / "profiles" / profile / "build" if profile else state(home) / "build"
    return (json.loads((folder / "inventory.json").read_text()),
            json.loads((folder / "wortlaut.json").read_text()))


def check(capsys):
    assert main(["check"]) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["systemMessage"] if out else ""


# ---------- config ----------
def test_without_profile_the_profile_table_changes_nothing(home, conf):
    conf(TEAM)
    cfg = load_config()
    assert cfg.profile is None and cfg.title == "Skill-Landkarte" and cfg.artifact_url is None
    assert set(cfg.withhold_text) == {"zeit", "plain"}


def test_profile_overrides_title_address_and_releases_texts(home, conf):
    conf(TEAM)
    cfg = load_config(profile="team")
    assert cfg.profile == "team"
    assert cfg.title == "Karte (Team)" and cfg.artifact_url == "https://example.invalid/team"
    assert set(cfg.withhold_text) == {"zeit"}
    assert cfg.vault == home / "vault"                       # everything else comes from the base


def test_profile_hint_names_the_profile_unless_the_base_sets_one(home, conf):
    conf(TEAM)
    assert load_config(profile="team").refresh_hint == (
        "skill-map --profile team build && skill-map --profile team mark-published")
    conf('refresh_hint = "/aktualisieren"\n' + TEAM)
    assert load_config(profile="team").refresh_hint == "/aktualisieren"


@pytest.mark.parametrize("text, words", [
    ("[profiles.team]\nvault = \"~/x\"\n", ["profiles.team", "vault"]),
    ("withhold_text = [\"zeit\"]\n[profiles.team]\nrelease_text = [\"other\"]\n", ["release_text", "other"]),
    ("[profiles.team]\nrelease_text = \"zeit\"\n", ["profiles.team", "release_text"]),
    ("[profiles.\"Team X\"]\ntitle = \"t\"\n", ["Team X"]),
    ("profiles = 3\n", ["profiles"]),
])
def test_bad_profiles_are_config_errors(home, conf, text, words):
    conf(text)
    with pytest.raises(ConfigError) as e:
        load_config()
    for w in words:
        assert w in str(e.value)


def test_unknown_profile_is_an_error_naming_it(home, conf, capsys):
    conf(TEAM)
    with pytest.raises(ConfigError, match="nope"):
        load_config(profile="nope")
    assert main(["--profile", "nope", "build"]) == 2
    assert "nope" in capsys.readouterr().err


def test_check_refuses_a_profile(home, conf, capsys):
    conf(TEAM)
    assert main(["--profile", "team", "check"]) == 2
    assert "every published profile" in capsys.readouterr().err


def test_state_dir_per_profile(home):
    assert state_dir() == state(home)
    assert state_dir("team") == state(home) / "profiles" / "team"


# ---------- build ----------
def test_profile_build_shows_the_released_text_and_keeps_the_rest(world, home, conf, capsys):
    conf(TEAM)
    assert main(["build"]) == 0
    assert main(["--profile", "team", "build"]) == 0
    inv, wl = built(home)
    assert set(wl["entries"]["plain"]) == {"withheld"} and inv["entries"]["plain"]["desc"] == ""
    inv, wl = built(home, "team")
    assert wl["entries"]["plain"] == {"text": "---\ndescription: Ein einfacher Befehl\n---\nplain\n"}
    assert inv["entries"]["plain"]["desc"] == "Ein einfacher Befehl"
    assert inv["title"] == "Karte (Team)"
    assert set(wl["entries"]["zeit"]) == {"withheld"}            # not released
    assert "vertraulich" in wl["entries"]["rb-c"]["withheld"]    # a classification is never released


def test_release_cannot_lift_a_classification(world, home, conf, capsys):
    conf(CONFIG.replace('withhold_text = ["zeit"]', 'withhold_text = ["zeit", "rb-c"]')
         + '[profiles.team]\nrelease_text = ["rb-c"]\n')
    assert main(["--profile", "team", "build"]) == 0
    inv, wl = built(home, "team")
    assert "vertraulich" in wl["entries"]["rb-c"]["withheld"]
    assert inv["entries"]["rb-c"]["desc"] == ""


# ---------- state ----------
def test_profile_state_is_separate_from_the_default(world, home, conf, capsys):
    conf(TEAM)
    assert main(["build"]) == 0 and main(["mark-published"]) == 0
    before = (state(home) / "published" / "fingerprint.json").read_bytes()
    assert main(["--profile", "team", "build"]) == 0
    assert main(["--profile", "team", "mark-published"]) == 0
    assert (state(home) / "published" / "fingerprint.json").read_bytes() == before
    assert (state(home) / "profiles/team/published/fingerprint.json").is_file()
    assert not (state(home) / "profiles/team/published.prev").exists()
    capsys.readouterr()
    assert main(["--profile", "team", "diff"]) == 0
    out = capsys.readouterr().out
    withheld = out.split("\nwithheld (", 1)[1].splitlines()[1:]
    assert "new (0)" in out and not any(l.startswith("  plain:") for l in withheld)   # plain is shown here
    assert any(l.startswith("  zeit:") for l in withheld)


def test_diff_and_mark_published_of_a_profile_need_its_own_build(world, home, conf, capsys):
    conf(TEAM)
    assert main(["build"]) == 0
    assert main(["--profile", "team", "diff"]) == 1
    assert main(["--profile", "team", "mark-published"]) == 1
    assert "profiles/team/build" in capsys.readouterr().err


def test_check_reports_published_profiles_only(world, home, conf, capsys):
    conf(TEAM)
    assert main(["build"]) == 0 and main(["mark-published"]) == 0
    capsys.readouterr()
    assert check(capsys) == ""                                   # team never published: not nagged
    assert main(["--profile", "team", "build"]) == 0 and main(["--profile", "team", "mark-published"]) == 0
    capsys.readouterr()
    assert check(capsys) == ""
    (home / ".claude/commands/neu.md").write_text("x\n")
    lines = check(capsys).split("\n")
    assert lines == [
        "Skill-Landkarte veraltet (neu: neu) – skill-map build && skill-map mark-published",
        "Karte (Team) veraltet (neu: neu) – skill-map --profile team build && skill-map --profile team mark-published",
    ]


# ---------- runbook texts ----------
RB = TEAM.replace('release_text = ["plain"]', 'release_text = ["plain"]\nrunbook_text = true')


def test_runbook_text_is_off_by_default_and_in_a_profile_without_the_switch(world, home, conf, capsys):
    conf(TEAM)
    assert main(["build"]) == 0 and main(["--profile", "team", "build"]) == 0
    for profile in (None, "team"):
        inv, wl = built(home, profile)
        assert inv["entries"]["runbook:rb-a"]["text"] == "none" and "runbook:rb-a" not in wl["entries"]


def test_profile_with_runbook_text_shows_the_runbook_unchanged(world, home, conf, capsys):
    conf(RB)
    body = "---\ntitle: Runbook A\ncommand: rb-a\nstatus: aktiv\ntags: [runbook, arbeit, git]\n---\n\n## Ablauf\n1. tun\n"
    (home / "vault/40-runbooks/rb-a.md").write_text(body)
    assert main(["build"]) == 0 and main(["--profile", "team", "build"]) == 0
    inv, wl = built(home)
    assert inv["entries"]["runbook:rb-a"]["text"] == "none"            # the default page is unchanged
    inv, wl = built(home, "team")
    assert inv["entries"]["runbook:rb-a"]["text"] == "shown"
    assert wl["entries"]["runbook:rb-a"] == {"text": body}


def test_runbook_text_follows_the_rules_of_its_command_and_its_own_classification(world, home, conf, capsys):
    conf(RB.replace('withhold_text = ["zeit", "plain"]', 'withhold_text = ["zeit", "plain", "rb-a"]'))
    (home / "vault/40-runbooks/rb-a.md").write_text(
        "---\ntitle: Runbook A\ncommand: rb-a\nstatus: aktiv\n---\nNAME-EINER-PERSON\n")
    assert main(["--profile", "team", "build"]) == 0
    inv, wl = built(home, "team")
    assert "NAME-EINER-PERSON" not in json.dumps(wl, ensure_ascii=False)
    assert inv["entries"]["runbook:rb-a"]["text"] == "withheld"
    assert "vertraulich" in wl["entries"]["runbook:rb-c"]["withheld"]   # classification: sensitive


def test_runbook_of_a_hidden_withheld_command_stays_withheld(world, home, conf, capsys):
    conf(RB.replace('withhold_text = ["zeit", "plain"]', 'withhold_text = ["zeit", "plain", "rb-a"]\nhide = ["rb-a"]'))
    (home / "vault/40-runbooks/rb-a.md").write_text(
        "---\ntitle: Runbook A\ncommand: rb-a\nstatus: aktiv\n---\nNAME-EINER-PERSON\n")
    assert main(["--profile", "team", "build"]) == 0
    inv, wl = built(home, "team")
    assert "NAME-EINER-PERSON" not in json.dumps(wl, ensure_ascii=False)


def test_runbook_text_must_be_true_or_false(home, conf):
    conf('[profiles.team]\nrunbook_text = "yes"\n')
    with pytest.raises(ConfigError, match="runbook_text"):
        load_config()
