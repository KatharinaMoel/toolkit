import hashlib

from skill_map.config import Config
from skill_map.texts import text_for

FAKE_ID = "00000000-1111-4222-8333-444444444444"


def write(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_shown_text_is_the_file_unchanged(home):
    data = b"---\ndescription: d\n---\r\nline one\r\nno final newline"
    f = write(home / ".claude/commands/crlf.md", data)
    r = text_for("crlf", f, Config(), None)
    assert r.status == "shown"
    assert r.text.encode("utf-8") == data
    assert r.withheld is None
    assert r.sha256 == hashlib.sha256(data).hexdigest()


def test_config_withholds_with_default_or_own_reason(home):
    f = write(home / ".claude/skills/zeit/SKILL.md", b"---\nname: zeit\n---\nprivate\n")
    r = text_for("zeit", f, Config(withhold_text={"zeit": None}), None)
    assert r.status == "withheld" and r.text is None
    assert "enthält persönliche Angaben" in r.withheld
    assert "~/.claude/skills/zeit/SKILL.md" in r.withheld
    assert r.sha256 == hashlib.sha256(f.read_bytes()).hexdigest()
    r = text_for("zeit", f, Config(withhold_text={"zeit": "Zeitkonto"}), None)
    assert "Zeitkonto" in r.withheld


def test_sensitive_file_or_source_note_is_withheld(home):
    own = write(home / "a.md", b"---\nclassification: secret\n---\nx\n")
    assert "als vertraulich eingestuft" in text_for("a", own, Config(), None).withheld
    note = write(home / "notes/40-runbooks/rb-c.md", b"---\nclassification: sensitive\n---\nx\n")
    cmd = write(home / ".claude/commands/rb-c.md", b"generated command\n")
    r = text_for("rb-c", cmd, Config(), note)
    assert r.status == "withheld" and "als vertraulich eingestuft" in r.withheld
    internal = write(home / "notes/40-runbooks/rb-a.md", b"---\nclassification: internal\n---\n")
    assert text_for("rb-a", cmd, Config(), internal).status == "shown"


def test_invalid_utf8_and_account_id_are_withheld(home):
    bad = write(home / "bad.md", b"caf\xe9\n")
    r = text_for("bad", bad, Config(), None)
    assert r.status == "withheld" and "keine gültige UTF-8-Datei" in r.withheld
    uid = write(home / "uid.md", f"see {FAKE_ID}\n".encode())
    r = text_for("uid", uid, Config(), None)
    assert r.status == "withheld" and "enthält eine Konto-ID" in r.withheld
    assert FAKE_ID not in r.withheld


def test_first_rule_wins(home):
    f = write(home / "both.md", b"---\nclassification: secret\n---\ncaf\xe9\n")
    r = text_for("both", f, Config(withhold_text={"both": None}), None)
    assert "enthält persönliche Angaben" in r.withheld
