import io
from pathlib import Path

import pytest

from transcribe import cli, feed, ui

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def show():
    return feed.parse_feed((FIXTURES / "feed.xml").read_bytes(), "https://feeds.example.org/x")


def test_permission_notice_prints_copyright_license_and_personal_use(capsys):
    assert cli.permission(show(), assume_yes=True, stdin=io.StringIO("")) is True
    err = capsys.readouterr().err
    assert "(c) 2025 Example Media" in err
    assert "cc-by-nc-4.0" in err
    assert "Transkripte sind nur für den persönlichen Gebrauch; nicht veröffentlichen." in err


@pytest.mark.parametrize("answer,ok", [("\n", True), ("j\n", True), ("J\n", True), ("ja\n", True),
                                       ("n\n", False), ("nein\n", False), ("x\n", False)])
def test_permission_answers(answer, ok, capsys):
    stdin = io.StringIO(answer)
    stdin.isatty = lambda: True
    assert cli.permission(show(), assume_yes=False, stdin=stdin) is ok
    assert "Weiter? [J/n]" in capsys.readouterr().err


def test_permission_without_terminal_needs_yes():
    with pytest.raises(ui.Abort, match="--yes"):
        cli.permission(show(), assume_yes=False, stdin=io.StringIO(""))


def test_missing_copyright_is_said_not_hidden(capsys):
    s = feed.parse_feed((FIXTURES / "feed-newest-first.xml").read_bytes(), "https://f")
    cli.permission(s, assume_yes=True, stdin=io.StringIO(""))
    assert "kein <copyright>" in capsys.readouterr().err


def test_list_prints_numbered_episodes(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.net, "get", lambda url: (FIXTURES / "feed.xml").read_bytes())
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(tmp_path / "none"))
    assert cli.main(["list", "https://feeds.example.org/x", "--limit", "3"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "  1  2025-08-30    18:54  Episode 1: Welcome & Why It Matters"
    assert out[2] == "  3  2025-08-30  1:02:03  Episode 3: Inside the Exam"
    assert len(out) == 3


def test_list_marks_episode_without_audio(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.net, "get", lambda url: (FIXTURES / "feed.xml").read_bytes())
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(tmp_path / "none"))
    cli.main(["list", "https://feeds.example.org/x"])
    line = capsys.readouterr().out.splitlines()[3]
    assert "kein Audio" in line


def test_queue_add_range_and_status(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.net, "get", lambda url: (FIXTURES / "feed.xml").read_bytes())
    conf = tmp_path / "config"
    conf.write_text(f"STATE_FILE={tmp_path}/q.json\nOUT_DIR={tmp_path}/out\n")
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(conf))
    assert cli.main(["queue", "add", "https://feeds.example.org/x", "--range", "1-4", "--yes"]) == 0
    err = capsys.readouterr().err
    assert "3 neu" in err and "ohne Audio" in err  # item 4 has no enclosure
    assert cli.main(["queue", "status"]) == 0
    out = capsys.readouterr().out
    assert out.count("pending") == 3


def test_queue_add_needs_all_or_range(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(tmp_path / "none"))
    with pytest.raises(SystemExit):
        cli.main(["queue", "add", "https://feeds.example.org/x"])


def test_queue_run_on_empty_queue_says_nothing_to_do(monkeypatch, capsys, tmp_path):
    conf = tmp_path / "config"
    conf.write_text(f"STATE_FILE={tmp_path}/q.json\n")
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(conf))
    assert cli.main(["queue", "run"]) == 0
    assert "Nichts zu tun" in capsys.readouterr().err


def test_resolve_refusal_exit_code(monkeypatch, capsys, tmp_path):
    def fail(url, http):
        raise cli.resolve.ResolveError("kein öffentlicher Feed gefunden – Spotify-exklusiv")
    monkeypatch.setattr(cli.resolve, "resolve_url", fail)
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(tmp_path / "none"))
    assert cli.main(["resolve", "https://open.spotify.com/show/abc"]) == 1
    assert "kein öffentlicher Feed gefunden" in capsys.readouterr().err


def test_status_tells_stale_running_from_active_run(monkeypatch, capsys, tmp_path):
    from transcribe import queue as q
    conf = tmp_path / "config"
    conf.write_text(f"STATE_FILE={tmp_path}/q.json\n")
    monkeypatch.setenv("TRANSCRIBE_CONFIG", str(conf))
    state = q.Queue(tmp_path / "q.json")
    state.add({"feed_url": "https://f", "guid": "g", "index": 1, "title": "T"})
    state.mark_running(q.key("https://f", "g"))
    state.save()
    cli.main(["queue", "status"])
    assert "kein Lauf aktiv" in capsys.readouterr().err
    with q.locked(tmp_path / "q.json"):
        cli.main(["queue", "status"])
    assert "Lauf ist gerade aktiv" in capsys.readouterr().err
