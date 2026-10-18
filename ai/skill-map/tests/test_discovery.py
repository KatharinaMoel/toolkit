import json

import pytest

from skill_map.config import load_config
from skill_map.discovery import DiscoveryError, discover
from world import FAKE_ID


@pytest.fixture
def w(world):
    return discover(load_config())


def test_local_entries_keys_kinds_places_calls(w, home):
    e = w.entries
    assert e["plain"].kind == "command" and e["plain"].place == "personal-commands"
    assert e["plain"].call == "/plain" and e["plain"].desc == "Ein einfacher Befehl"
    assert e["plain"].path == home / ".claude/commands/plain.md"
    assert e["alpha"].kind == "skill" and e["alpha"].place == "personal-skills"
    assert e["linked"].path == home / ".claude/skills/linked/SKILL.md"
    assert e["sub:subcmd"].call == "/sub:subcmd"
    assert e["mgd"].place == "managed"
    assert e["projcmd"].place == "project:1" and e["projskill"].place == "project:1"
    assert e["agent:helper"].kind == "agent" and e["agent:helper"].call == "helper"


def test_shadowed_entries_get_a_place_suffix(w):
    e = w.entries
    assert "shadowed" not in e["start"].flags and e["start"].place == "personal-commands"
    assert e["start@project:1"].place == "project:1" and "shadowed" in e["start@project:1"].flags
    assert e["alpha"].kind == "skill"                       # the skill wins over the command
    assert "shadowed" in e["alpha@personal-commands"].flags


def test_never_listed(w):
    keys = set(w.entries)
    for gone in ("old", "superp:oldskill", "eng:old-review", "runbook:_guide"):
        assert gone not in keys
    assert not any(".bucket" in k for k in keys)


def test_plugins_prefix_version_agents_disabled(w, world):
    e = w.entries
    assert e["superp:brainstorming"].call == "/superp:brainstorming"
    assert e["superp:brainstorming"].group == "plugin:superp" and e["superp:brainstorming"].version == "7.0.0"
    assert e["ai:building-agents"].group == "plugin:ai"            # prefix from plugin.json, not the folder
    assert e["reviewkit:review"].kind == "command"
    assert e["agent:reviewkit:code-reviewer"].call == "reviewkit:code-reviewer"
    assert e["agent:reviewkit:code-reviewer"].version == "abc123def456"
    assert "disabled" in e["offplug:offskill"].flags
    assert "disabled" not in e["superp:tdd"].flags


def test_origin_vendor_version_links_never_email(w):
    g = {x.id: x for x in w.groups}
    o = g["plugin:superp"].origin
    assert o["vendor"] == "Jane Vendor" and o["version"] == "7.0.0" and o["marketplace"] == "mkt"
    assert o["installed"] == "2026-09-01"
    assert o["homepage"] == "https://example.invalid/superp" and o["repository"] is None
    assert g["plugin:reviewkit"].origin["vendor"] == "Review People"
    assert g["plugin:reviewkit"].origin["version"] == "abc123def456"
    assert g["plugin:superp"].counts == {"skill": 2, "command": 0, "agent": 0}
    assert "jane@example.invalid" not in json.dumps([x.origin for x in w.groups])


def test_claude_ai_skills_and_plugins(w):
    e = w.entries
    assert e["anthropic-skills:pdf"].place == "claude-ai"
    assert e["eng:code-review"].place == "claude-ai" and e["eng:code-review"].version == "g3"
    g = {x.id: x for x in w.groups}
    assert g["claude-ai:eng"].origin["type"] == "claude.ai" and g["claude-ai:eng"].origin["marketplace"] is None


def test_kios_source_and_missing_source(w):
    e = w.entries
    assert e["k-start"].source_note == "templates/k-start.md" and "source-missing" not in e["k-start"].flags
    assert e["rb-a"].source_note == "40-runbooks/rb-a.md" and "source-missing" not in e["rb-a"].flags
    assert "source-missing" in e["gone"].flags
    assert e["plain"].source_note is None


def test_runbooks(w):
    e = w.entries
    a, b = e["runbook:rb-a"], e["runbook:rb-b"]
    assert a.kind == "runbook" and a.place == "vault-runbooks" and a.desc == "Runbook A" and a.call == "/rb-a"
    assert a.runbook == {"status": "aktiv", "tags": ["runbook", "arbeit", "git"], "area": "Arbeit",
                         "command": "rb-a", "command_entry": "rb-a"}
    assert e["rb-a"].runbook == "runbook:rb-a" and "draft" not in e["rb-a"].flags
    assert b.runbook["command_entry"] is None and "no-command" in b.flags and "draft" in b.flags
    assert e["runbook:rb-c"].runbook["area"] is None


def test_draft_is_inherited_by_the_generated_command(world, home):
    (home / "vault/40-runbooks/rb-a.md").write_text("---\ntitle: A\ncommand: rb-a\nstatus: entwurf\n---\n")
    w = discover(load_config())
    assert "draft" in w.entries["rb-a"].flags


def test_hooks_tools_builtins(w, home):
    e = w.entries
    h = e["hook:SessionStart:boundary.sh"]
    assert h.kind == "hook" and h.call == "SessionStart" and h.desc == "Startort prüfen"
    assert h.path == home / ".claude/hooks/boundary.sh"
    assert "hook:Stop:stop.py" in e
    assert e["hook:PreToolUse:guard.sh"].place == "hooks"
    assert e["tool:wt"].desc == "disposable git worktrees" and e["tool:wt"].call == "wt"
    assert "tool:show" in e and "tool:notatool" not in e
    assert e["builtin:code-review"].desc == "Review des aktuellen Diffs" and e["builtin:code-review"].path is None


def test_places_in_lane_order_without_empty_ones(w):
    assert [p.id for p in w.places] == ["vault-runbooks", "personal-commands", "plugins", "claude-ai",
                                        "personal-skills", "project:1", "toolkit", "hooks", "builtins", "managed"]
    proj = [p for p in w.places if p.id == "project:1"][0]
    assert proj.title == "Proj" and proj.path == "~/proj/.claude/"


def test_paths_never_carry_the_account_id(w):
    from skill_map.paths import tilde
    for p in w.places:
        assert FAKE_ID not in p.path
    assert "<konto>" in tilde(w.entries["anthropic-skills:pdf"].path)


def test_hide_removes_entries(world, conf):
    from world import CONFIG
    conf(CONFIG.replace('withhold_text = ["zeit"]', 'withhold_text = ["zeit"]\nhide = ["agent:*", "plain"]'))
    keys = set(discover(load_config()).entries)
    assert "plain" not in keys and not any(k.startswith("agent:") for k in keys)


def test_zero_config_shows_only_claude_code_places(world, home):
    (home / ".config/skill-map/skill-map.conf").unlink()
    w = discover(load_config())
    places = {p.id for p in w.places}
    assert {"vault-runbooks", "project:1", "toolkit", "builtins"}.isdisjoint(places)
    assert "plain" in w.entries and "superp:tdd" in w.entries
    assert not any(k.startswith(("runbook:", "tool:", "builtin:")) for k in w.entries)


def test_broken_installed_plugins_is_an_error(world, home):
    (home / ".claude/plugins/installed_plugins.json").write_text("{broken")
    with pytest.raises(DiscoveryError, match="installed_plugins.json"):
        discover(load_config())


def test_missing_installed_plugins_is_fine(world, home):
    (home / ".claude/plugins/installed_plugins.json").unlink()
    assert "superp:tdd" not in discover(load_config()).entries


def test_unreadable_file_is_listed_with_a_note(world, home):
    f = home / ".claude/commands/plain.md"
    f.chmod(0)
    try:
        w = discover(load_config())
    finally:
        f.chmod(0o644)
    assert "plain" in w.entries
    assert any("plain.md" in n for n in w.notes)


def test_a_plugin_without_entries_keeps_its_group(w):
    g = {x.id: x for x in w.groups}
    assert g["plugin:emptyplug"].counts == {"skill": 0, "command": 0, "agent": 0}
    assert g["plugin:emptyplug"].origin["vendor"] == "Hook Maker"


def test_source_prefixes_map_a_raw_value_to_another_folder(world, home, conf):
    from world import CONFIG, MARK, put
    put(home / ".claude/commands/mapped.md", "---\ndescription: m\n---\n" + MARK.format("templates/mapped.md") + "\n")
    put(home / "gen/agent/system-commands/mapped.md", "template\n")
    w = discover(load_config())
    assert "source-missing" in w.entries["mapped"].flags
    conf(CONFIG.replace("[[projects]]", '[source_prefixes]\n"templates/" = "~/gen/agent/system-commands/"\n\n[[projects]]', 1))
    w = discover(load_config())
    assert "source-missing" not in w.entries["mapped"].flags
    assert w.entries["mapped"].source_path == home / "gen/agent/system-commands/mapped.md"
    assert "source-missing" not in w.entries["k-start"].flags        # roots still work


def test_hooks_without_a_clear_script_are_listed_without_their_command(world, home):
    s = home / ".claude/settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["Notification"] = [{"hooks": [
        {"type": "command", "command": 'if [ -n "$X" ]; then printf hidden-text; fi', "statusMessage": "Orca"},
        {"type": "command", "command": "notify-send other-hidden-text"}]}]
    s.write_text(json.dumps(data))
    w = discover(load_config())
    inline = sorted(k for k in w.entries if k.startswith("hook:Notification:"))
    assert len(inline) == 2 and all(w.entries[k].path is None for k in inline)
    assert w.entries[inline[0]].desc == "Orca" or w.entries[inline[1]].desc == "Orca"
    assert "hidden-text" not in json.dumps([vars(e) for e in w.entries.values()], default=str)
