import hashlib
import json

import pytest

from skill_map.build import build, fingerprint
from skill_map.cli import main
from skill_map.config import load_config
from skill_map.discovery import discover
from test_usage import write_logs
from world import FAKE_ID, FAKE_PAIR


def run_build(tmp_path, logs=None):
    lines = []
    out = build(load_config(), tmp_path / "out", lines.append)
    inv = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    wl = json.loads((out / "wortlaut.json").read_text(encoding="utf-8"))
    return inv, wl, lines


def test_inventory_shape(world, home, tmp_path):
    inv, wl, _ = run_build(tmp_path)
    assert inv["schema"] == 1 and inv["title"] == "Skill-Landkarte"
    assert inv["fingerprint"].startswith("sha256:")
    assert list(inv["entries"]) == sorted(inv["entries"])
    b = inv["entries"]["superp:brainstorming"]
    path = world["superp"] / "skills/brainstorming/SKILL.md"
    assert b == {"name": "brainstorming", "call": "/superp:brainstorming", "kind": "skill",
                 "group": "plugin:superp", "place": "plugins", "desc": "Ideas first",
                 "path": "~/.claude/plugins/cache/mkt/superp/7.0.0/skills/brainstorming/SKILL.md",
                 "runbook": None, "source_note": None, "usage": {"count": 0, "last": None},
                 "text": "shown", "text_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "flags": []}
    assert [p["id"] for p in inv["places"]][:3] == ["vault-runbooks", "personal-commands", "plugins"]
    assert {"id", "title", "place", "origin", "counts"} <= set(inv["groups"][0])
    assert inv["entries"]["hook:Stop:stop.py"]["text"] == "none"
    assert inv["entries"]["runbook:rb-a"]["text_sha256"] is None
    assert inv["narrative"] == {"missing_keys": []}


def test_texts_one_to_one_and_withheld(world, home, tmp_path):
    inv, wl, _ = run_build(tmp_path)
    assert wl["schema"] == 1
    plain = home / ".claude/commands/plain.md"
    assert wl["entries"]["plain"] == {"text": plain.read_text(encoding="utf-8")}
    assert set(wl["entries"]["zeit"]) == {"withheld"} and "persönliche Angaben" in wl["entries"]["zeit"]["withheld"]
    assert inv["entries"]["zeit"]["text"] == "withheld" and "withheld" in inv["entries"]["zeit"]["flags"]
    assert "vertraulich" in wl["entries"]["rb-c"]["withheld"]          # sensitive kios source
    assert "private numbers" not in json.dumps(wl)
    assert "runbook:rb-a" not in wl["entries"] and "hook:Stop:stop.py" not in wl["entries"]


def test_no_account_id_anywhere(world, home, tmp_path):
    (home / ".claude/commands/uid.md").write_text(f"id {FAKE_ID}\n")
    run_build(tmp_path)
    for name in ("inventory.json", "wortlaut.json"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert FAKE_ID not in text and FAKE_PAIR not in text
    inv = json.loads((tmp_path / "out/inventory.json").read_text())
    assert "<konto>" in inv["entries"]["anthropic-skills:pdf"]["path"]
    assert inv["entries"]["uid"]["text"] == "withheld"


def test_usage_and_runbook_usage(world, home, tmp_path):
    write_logs(home)
    inv, _, _ = run_build(tmp_path)
    e = inv["entries"]
    assert e["k-start"]["usage"] == {"count": 2, "last": "2026-10-05"}
    assert inv["usage"]["since"] == "2026-09-04" and inv["usage"]["sessions"] == 2
    assert {"name": "/model", "count": 1, "last": "2026-09-04"} in inv["usage"]["unmatched"]
    assert e["runbook:rb-a"]["usage"] == e["rb-a"]["usage"]
    assert "method" in inv["usage"]


def test_hide_removes_from_both_files_and_the_fingerprint(world, conf, tmp_path):
    from world import CONFIG
    before = fingerprint(discover(load_config()))[0]
    conf(CONFIG.replace('withhold_text = ["zeit"]', 'withhold_text = ["zeit"]\nhide = ["plain"]'))
    inv, wl, _ = run_build(tmp_path)
    assert "plain" not in inv["entries"] and "plain" not in wl["entries"]
    assert inv["fingerprint"] != before


def test_fingerprint_rules(world, home):
    fp = lambda: fingerprint(discover(load_config()))[0]
    first = fp()
    assert fp() == first
    write_logs(home)
    assert fp() == first                                          # usage is not in it
    (home / ".claude/commands/plain.md").write_text("---\ndescription: changed\n---\nnew text\n")
    assert fp() == first                                          # texts and descriptions are not in it
    (home / ".claude/commands/new.md").write_text("new\n")
    added = fp()
    assert added != first
    (home / ".claude/commands/new.md").unlink()
    assert fp() == first
    inst = home / ".claude/plugins/installed_plugins.json"
    inst.write_text(inst.read_text().replace('"version": "7.0.0"', '"version": "7.1.0"'))
    assert fp() != first


def test_fingerprint_independent_of_creation_order(world, home):
    a, b = home / ".claude/commands/zz-a.md", home / ".claude/commands/zz-b.md"
    a.write_text("a\n"); b.write_text("b\n")
    one = fingerprint(discover(load_config()))
    a.unlink(); b.unlink()
    b.write_text("b\n"); a.write_text("a\n")
    assert fingerprint(discover(load_config())) == one
    assert ["plain", "command", "personal-commands", ""] in one[1]


def test_explains_what_it_reads_and_writes(world, tmp_path):
    _, _, lines = run_build(tmp_path)
    text = "\n".join(lines)
    assert "reading ~/.claude/plugins/installed_plugins.json" in text
    assert "writing" in text and "inventory.json" in text


def test_cli_build_and_fingerprint(world, tmp_path, capsys):
    assert main(["build", "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o/inventory.json").is_file()
    capsys.readouterr()
    assert main(["fingerprint"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("sha256:") and "plain\tcommand\tpersonal-commands\t" in out


def test_cli_build_broken_plugins_exits_1(world, home, tmp_path, capsys):
    (home / ".claude/plugins/installed_plugins.json").write_text("{")
    assert main(["build", "--out", str(tmp_path / "o")]) == 1
    assert "installed_plugins.json" in capsys.readouterr().err


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root reads everything")
def test_unreadable_file_is_withheld_not_fatal(world, home, tmp_path):
    f = home / ".claude/commands/plain.md"
    f.chmod(0)
    try:
        inv, wl, _ = run_build(tmp_path)
    finally:
        f.chmod(0o644)
    assert inv["entries"]["plain"]["text"] == "withheld"
    assert "nicht lesbar" in wl["entries"]["plain"]["withheld"]


def test_account_id_in_a_description_is_replaced(world, home, tmp_path):
    (home / ".claude/commands/iddesc.md").write_text(f"---\ndescription: see {FAKE_ID}\n---\nx\n")
    run_build(tmp_path)
    inv = (tmp_path / "out/inventory.json").read_text(encoding="utf-8")
    assert FAKE_ID not in inv and "see <konto>" in inv


def test_classified_files_publish_no_description_or_title(world, home, tmp_path):
    (home / ".claude/commands/secret.md").write_text(
        "---\ndescription: SECRET-DESC\nclassification: secret\n---\nx\n")
    (home / "vault/40-runbooks/rb-c.md").write_text(
        "---\ntitle: GEHEIMER-TITEL\ncommand: rb-c\nstatus: aktiv\nclassification: sensitive\ntags: [geheim-tag]\n---\n")
    (home / ".claude/commands/rb-c.md").write_text(
        "---\ndescription: VERTRAULICH-DESC\n---\n<!-- kios:generated | Quelle: 40-runbooks/rb-c.md | x -->\n")
    inv, wl, _ = run_build(tmp_path)
    dumped = json.dumps([inv, wl], ensure_ascii=False)
    for secret in ("SECRET-DESC", "GEHEIMER-TITEL", "geheim-tag", "VERTRAULICH-DESC"):
        assert secret not in dumped
    assert inv["entries"]["runbook:rb-c"]["runbook"]["tags"] == []


def test_unresolvable_source_note_withholds_the_text(world, home, tmp_path):
    inv, wl, _ = run_build(tmp_path)
    assert "source-missing" in inv["entries"]["gone"]["flags"]
    assert inv["entries"]["gone"]["text"] == "withheld"
    assert "Einstufung unbekannt" in wl["entries"]["gone"]["withheld"]
    assert inv["entries"]["k-start"]["text"] == "shown"            # resolved source, not classified


def test_unknown_source_hides_the_description_too(world, home, tmp_path):
    (home / ".claude/commands/gone.md").write_text(
        "---\ndescription: GONE-DESC\n---\n<!-- kios:generated | Quelle: templates/missing.md | x -->\n")
    inv, _, _ = run_build(tmp_path)
    assert inv["entries"]["gone"]["desc"] == ""


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root reads everything")
def test_unreadable_source_note_counts_as_classified(world, home, tmp_path):
    note = home / "vault/40-runbooks/rb-a.md"
    (home / ".claude/commands/rb-a.md").write_text(
        "---\ndescription: RBA-DESC\n---\n<!-- kios:generated | Quelle: 40-runbooks/rb-a.md | x -->\n")
    note.chmod(0)
    try:
        inv, wl, _ = run_build(tmp_path)
    finally:
        note.chmod(0o644)
    assert "RBA-DESC" not in json.dumps([inv, wl])
    assert inv["entries"]["rb-a"]["text"] == "withheld"


# ---------- final review ----------
def test_hook_command_with_an_inline_secret_never_leaks(world, home, tmp_path):
    # Made-up values, assembled at run time so the secret scanner of the hook stays quiet.
    token, var1, var2 = "-".join(["fake", "token", "value"]), "MY" + "_TOKEN", "MY" + "_KEY"
    s = home / ".claude/settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["Notification"] = [{"hooks": [
        {"type": "command", "command": f"{var1}={token} ~/.claude/hooks/notify.sh"},
        {"type": "command", "command": f"env {var2}={token}2 python3 ~/.claude/hooks/ping.py --loud"}]}]
    s.write_text(json.dumps(data))
    inv, wl, _ = run_build(tmp_path)
    page = (tmp_path / "out/skill-map.html").read_text(encoding="utf-8")
    for secret in (token, var1, var2):
        assert secret not in json.dumps(inv) and secret not in page
    assert "hook:Notification:notify.sh" in inv["entries"] and "hook:Notification:ping.py" in inv["entries"]


def test_embedded_json_cannot_open_a_double_escaped_script(world, home, tmp_path):
    (home / ".claude/commands/htmlhelp.md").write_text("Start a comment with <!-- and code with a <script> tag.\n")
    run_build(tmp_path)
    page = (tmp_path / "out/skill-map.html").read_text(encoding="utf-8")
    import re as _re
    block = _re.search(r'id="wortlaut-data">(.*?)</script>', page, _re.S).group(1)
    assert "<" not in block and ">" not in block
    assert json.loads(block)["entries"]["htmlhelp"]["text"].startswith("Start a comment with <!--")


def test_hiding_a_generated_command_unlinks_its_runbook(world, conf, tmp_path):
    from world import CONFIG
    conf(CONFIG.replace('withhold_text = ["zeit"]', 'withhold_text = ["zeit"]\nhide = ["rb-a"]'))
    inv, _, _ = run_build(tmp_path)
    rb = inv["entries"]["runbook:rb-a"]
    assert rb["runbook"]["command_entry"] is None and "no-command" in rb["flags"]


def test_shadowed_keys_never_overwrite_each_other(world, home, tmp_path):
    from world import skill
    skill(home / ".claude/skills/deploy", "deploy")
    skill(home / "proj/.claude/skills/deploy", "deploy")
    (home / "proj/.claude/commands/deploy.md").write_text("project command\n")
    inv, _, _ = run_build(tmp_path)
    deploy = sorted(k for k in inv["entries"] if k.split("@")[0] == "deploy")
    assert len(deploy) == 3
    assert {inv["entries"][k]["kind"] + "/" + inv["entries"][k]["place"] for k in deploy} == {
        "skill/personal-skills", "skill/project:1", "command/project:1"}


def test_account_ids_and_emails_never_in_any_field(world, home, tmp_path):
    s = home / ".claude/settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["PreToolUse"] = [{"matcher": f"mcp__{FAKE_ID}__x", "hooks": [
        {"type": "command", "command": "~/.claude/hooks/m.sh"}]}]
    s.write_text(json.dumps(data))
    pj = world["review"] / ".claude-plugin/plugin.json"
    mail = "people" + "@" + "example.invalid"
    pj.write_text(json.dumps({"name": "reviewkit", "author": f"Review People <{mail}>"}))
    inv, _, _ = run_build(tmp_path)
    dumped = json.dumps(inv)
    assert FAKE_ID not in dumped and mail not in dumped
    assert {g["id"]: g for g in inv["groups"]}["plugin:reviewkit"]["origin"]["vendor"] == "Review People"


def test_hook_commands_are_parsed_like_a_shell_and_fail_closed(world, home, tmp_path):
    part = "-".join(["fake", "quoted", "secret"])
    s = home / ".claude/settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["Notification"] = [{"hooks": [
        {"type": "command", "command": f'MY_VAR="{part} more" ~/.claude/hooks/q.sh'},
        {"type": "command", "command": f"/usr/bin/env -i MY_VAR={part} ~/.claude/hooks/e.sh"},
        {"type": "command", "command": f"echo '{part}"},                      # unbalanced quote
        {"type": "command", "command": f"{part}$(id) && x"}]}]
    s.write_text(json.dumps(data))
    inv, _, _ = run_build(tmp_path)
    page = (tmp_path / "out/skill-map.html").read_text(encoding="utf-8")
    assert part not in json.dumps(inv) and part not in page and "more" not in json.dumps(list(inv["entries"]))
    assert "hook:Notification:q.sh" in inv["entries"] and "hook:Notification:e.sh" in inv["entries"]


def test_only_path_like_words_name_a_hook_script(world, home, tmp_path):
    part = "-".join(["fake", "option", "value"])
    s = home / ".claude/settings.json"
    data = json.loads(s.read_text())
    data["hooks"]["Notification"] = [{"hooks": [
        {"type": "command", "command": f"node -e {part} ~/.claude/hooks/n.js"},
        {"type": "command", "command": f"env -u {part} ~/.claude/hooks/u.sh"},
        {"type": "command", "command": "notify-send hello"},
        {"type": "command", "command": "/usr/local/bin/my-tool check"}]}]
    s.write_text(json.dumps(data))
    inv, _, lines = run_build(tmp_path)
    assert part not in json.dumps(inv)
    assert "hook:Notification:my-tool" in inv["entries"]
    assert "hook:Notification:notify-send" not in inv["entries"]
    assert any("Notification hook" in line and "not listed" in line for line in lines)
