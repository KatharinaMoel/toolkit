import hashlib
import json
import os
import subprocess

import pytest

from conftest import LAUNCHER
from skill_map.cli import main


def state(home):
    return home / ".local/state/skill-map"


def check(capsys):
    assert main(["check"]) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["systemMessage"] if out else ""


def publish(capsys):
    assert main(["build"]) == 0
    assert main(["mark-published"]) == 0
    capsys.readouterr()


# ---------- mark-published ----------
def test_mark_published_copies_rotates_and_remembers(world, home, capsys):
    assert main(["mark-published"]) == 1                       # no build yet
    assert "build" in capsys.readouterr().err
    publish(capsys)
    pub = state(home) / "published"
    assert (pub / "inventory.json").is_file() and (pub / "index.html").is_file()
    fp = json.loads((pub / "fingerprint.json").read_text())
    assert fp["fingerprint"].startswith("sha256:") and ["plain", "command", "personal-commands", ""] in fp["set"]
    assert fp["texts"]["plain"] == hashlib.sha256((home / ".claude/commands/plain.md").read_bytes()).hexdigest()
    assert "zeit" not in fp["texts"]                           # withheld texts are not tracked
    publish(capsys)
    assert (state(home) / "published.prev/fingerprint.json").is_file()


def test_mark_published_refuses_a_stale_build(world, home, capsys):
    assert main(["build"]) == 0
    (home / ".claude/commands/later.md").write_text("added after the build\n")
    capsys.readouterr()
    assert main(["mark-published"]) == 1
    assert "run build again" in capsys.readouterr().err
    assert not (state(home) / "published").exists()


# ---------- diff ----------
def test_diff_lists_new_removed_changed_and_page(world, home, capsys):
    publish(capsys)
    (home / ".claude/commands/fresh.md").write_text("---\ndescription: neu\n---\nFRESH-TEXT\n")
    (home / ".claude/commands/start.md").unlink()
    (home / ".claude/commands/plain.md").write_text("---\ndescription: anders\n---\nCHANGED-TEXT\n")
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["diff"]) == 0
    out = capsys.readouterr().out
    assert "new (1): fresh" in out
    assert "removed (1): start" in out and "start@project:1" in out    # the project one is no longer shadowed
    assert "plain: desc, text_sha256" in out
    assert "page: unchanged" in out
    assert "withheld" in out and "zeit" in out


def test_diff_texts_prints_new_and_changed_shown_texts_only(world, home, capsys):
    publish(capsys)
    (home / ".claude/commands/fresh.md").write_text("FRESH-TEXT\nno final newline")
    (home / ".claude/skills/zeit/SKILL.md").write_text("---\nname: zeit\n---\nPRIVATE-CHANGED\n")
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["diff", "--texts"]) == 0
    out = capsys.readouterr().out
    assert "==> fresh · ~/.claude/commands/fresh.md\n──── begin ────\nFRESH-TEXT\nno final newline\n──── end of fresh (no newline at end of file) ────" in out
    assert "PRIVATE-CHANGED" not in out


def test_diff_without_publish_says_everything_is_new(world, capsys):
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["diff"]) == 0
    assert "never published" in capsys.readouterr().out


# ---------- check ----------
def test_check_states(world, home, capsys):
    assert check(capsys) == "Skill-Landkarte: noch nie veröffentlicht – skill-map build && skill-map mark-published"
    publish(capsys)
    assert check(capsys) == ""
    for n in ("a1", "a2", "a3", "a4"):
        (home / f".claude/commands/{n}.md").write_text("x\n")
    (home / ".claude/commands/plain.md").unlink()
    inst = home / ".claude/plugins/installed_plugins.json"
    inst.write_text(inst.read_text().replace('"version": "7.0.0"', '"version": "7.1.0"'))
    assert check(capsys) == ("Skill-Landkarte veraltet (neu: a1, a2, a3 +1; entfernt: plain; "
                             "geändert: superp 7.0.0→7.1.0) – skill-map build && skill-map mark-published")


def test_check_reports_changed_texts_on_their_own_quieter_line(world, home, capsys):
    publish(capsys)
    (home / ".claude/commands/k-start.md").write_text("changed text\n")
    (home / ".claude/skills/alpha/SKILL.md").write_text("---\nname: alpha\n---\nchanged\n")
    assert check(capsys) == "Skill-Landkarte: 2 Texte geändert – skill-map build && skill-map mark-published"
    (home / ".claude/commands/new.md").write_text("x\n")
    assert check(capsys) == "Skill-Landkarte veraltet (neu: new), 2 Texte geändert – skill-map build && skill-map mark-published"


def test_check_uses_title_and_refresh_hint(world, home, conf, capsys):
    from world import CONFIG
    conf('title = "Karte"\nrefresh_hint = "/karte-neu"\n' + CONFIG)
    assert check(capsys) == "Karte: noch nie veröffentlicht – /karte-neu"


@pytest.mark.parametrize("breakit", ["config", "plugins"])
def test_check_failure_is_one_line_and_exit_0(world, home, conf, capsys, breakit):
    publish(capsys)
    if breakit == "config":
        conf("title = [")
    else:
        (home / ".claude/plugins/installed_plugins.json").write_text('{"plugins": {"x@y": [{"installPa')
    assert check(capsys).startswith("Skill-Landkarte: Prüfung fehlgeschlagen (")


def test_check_never_reads_stdin_or_logs(world, home, capsys):
    publish(capsys)
    logs = home / ".claude/projects/-p"
    logs.mkdir(parents=True)
    os.mkfifo(logs / "s.jsonl")                                     # reading it would block
    r = subprocess.Popen([str(LAUNCHER), "check"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=dict(os.environ))
    try:
        out, err = r.communicate(timeout=10)                        # stdin stays open, never written
    finally:
        r.kill()
    assert r.returncode == 0 and out == b"", err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
def test_check_with_an_unreadable_skill_still_finishes(world, home, capsys):
    publish(capsys)
    f = home / ".claude/skills/alpha/SKILL.md"
    f.chmod(0)
    try:
        assert check(capsys) == ""
    finally:
        f.chmod(0o644)


def test_nothing_outside_the_state_folder_changes(world, home, capsys):
    def snapshot():
        out = {}
        for p in sorted(home.rglob("*")):
            if p.is_file() and state(home) not in p.parents:
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out
    before = snapshot()
    publish(capsys)
    main(["diff", "--texts"]); main(["check"]); main(["fingerprint"])
    capsys.readouterr()
    assert snapshot() == before


def test_diff_texts_also_prints_new_hand_written_metadata(world, home, capsys):
    publish(capsys)
    (home / "vault/40-runbooks/new-rb.md").write_text(
        "---\ntitle: TITEL-ZUM-LESEN\ncommand: new-rb\nstatus: entwurf\ntags: [runbook, TAG-ZUM-LESEN]\n---\n")
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["diff", "--texts"]) == 0
    out = capsys.readouterr().out
    assert "TITEL-ZUM-LESEN" in out and "TAG-ZUM-LESEN" in out


def test_default_hint_names_the_step_that_silences_the_line(world, capsys):
    msg = check(capsys)
    assert "skill-map mark-published" in msg
