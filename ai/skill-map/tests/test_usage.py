import json
import time

from skill_map.config import Config, load_config
from skill_map.discovery import discover
from skill_map.usage import count_usage

SENTINEL = "SENTINEL-LOG-TEXT-7f3a"


def user(uuid, ts, content):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "message": {"role": "user", "content": content}}


def tool(uuid, ts, name, **inp):
    return {"type": "assistant", "uuid": uuid, "timestamp": ts,
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def write_logs(home):
    proj = home / ".claude/projects/-proj"
    proj.mkdir(parents=True)
    s1 = [
        user("u1", "2026-10-01T12:00:00Z", "<command-name>/k-start</command-name>"),
        user("u2", "2026-10-02T12:00:00Z", [{"type": "text", "text": "<command-name>superp:brainstorming</command-name>"}]),
        tool("u3", "2026-10-03T12:00:00Z", "Skill", skill="superp:tdd"),
        tool("u4", "2026-10-03T12:00:00Z", "Skill", skill="alpha"),
        tool("u5", "2026-10-04T12:00:00Z", "Agent", subagent_type="reviewkit:code-reviewer"),
        tool("u6", "2026-10-04T12:00:00Z", "Task", subagent_type="Explore"),
        user("u7", "2026-10-04T12:00:00Z", "<command-name>/code-review</command-name>"),
        user("u8", "2026-10-04T12:00:00Z", "<command-name>free text with spaces</command-name>"),
        user("u9", "2026-10-04T12:00:00Z", "please " + SENTINEL),
        user("u10", "2026-10-05T12:00:00Z", "<command-name>/k-start</command-name>"),
    ]
    lines = [json.dumps(x) for x in s1]
    lines.insert(8, '{"type": "user", "message": "<command-name>/broken')       # malformed line
    (proj / "s1.jsonl").write_text("\n".join(lines) + "\n")
    s2 = [user("u1", "2026-10-01T12:00:00Z", "<command-name>/k-start</command-name>"),   # copied by a resume
          user("u11", "2026-09-04T12:00:00Z", "<command-name>/model</command-name>")]
    (proj / "s2.jsonl").write_text("\n".join(json.dumps(x) for x in s2) + "\n")
    sub = proj / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "a.jsonl").write_text(json.dumps(user("u12", "2026-10-06T12:00:00Z", "<command-name>/k-start</command-name>")) + "\n")
    return home / ".claude/projects"


def test_counts_last_dates_and_unmatched(world, home):
    logs = write_logs(home)
    r = count_usage(discover(load_config()), logs)
    assert r.counts["k-start"] == (2, "2026-10-05")        # duplicate uuid once, subagent log ignored
    assert r.counts["superp:brainstorming"] == (1, "2026-10-02")
    assert r.counts["superp:tdd"] == (1, "2026-10-03")
    assert r.counts["alpha"] == (1, "2026-10-03")
    assert r.counts["agent:reviewkit:code-reviewer"] == (1, "2026-10-04")
    assert r.counts["builtin:code-review"] == (1, "2026-10-04")
    unmatched = {u["name"]: u["count"] for u in r.unmatched}
    assert unmatched == {"Explore": 1, "/model": 1}
    assert r.since == "2026-09-04" and r.sessions == 2 and r.skipped == 1


def test_without_builtins_the_command_is_unmatched(world, home):
    logs = write_logs(home)
    cfg = load_config()
    cfg.builtins = {}
    r = count_usage(discover(cfg), logs)
    assert {"name": "/code-review", "count": 1, "last": "2026-10-04"} in r.unmatched


def test_no_log_text_leaks(world, home):
    logs = write_logs(home)
    r = count_usage(discover(load_config()), logs)
    dumped = json.dumps([r.counts, r.unmatched, r.since])
    assert SENTINEL not in dumped and "free text" not in dumped and "broken" not in dumped


def test_no_logs_folder(home):
    r = count_usage(discover(Config()), home / ".claude/projects")
    assert r.counts == {} and r.sessions == 0 and r.since is None


def test_large_log_is_streamed_quickly(world, home):
    proj = home / ".claude/projects/-big"
    proj.mkdir(parents=True)
    filler = json.dumps(user("x", "2026-10-01T12:00:00Z", "just talking " * 20))
    with (proj / "big.jsonl").open("w") as f:
        for i in range(50_000):
            f.write(filler.replace('"x"', f'"x{i}"') + "\n")
        f.write(json.dumps(user("last", "2026-10-07T12:00:00Z", "<command-name>/plain</command-name>")) + "\n")
    t = time.monotonic()
    r = count_usage(discover(load_config()), home / ".claude/projects")
    assert time.monotonic() - t < 2
    assert r.counts["plain"] == (1, "2026-10-07")
