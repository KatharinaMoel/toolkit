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
