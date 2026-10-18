"""How often each entry was used, from Claude Code's session logs (an approximation).

Counted: slash commands (<command-name> in user messages), skills (Skill tool calls)
and agents (Agent or Task tool calls with subagent_type), in the top-level session
logs only. A line whose uuid was already seen is skipped, so resumed sessions that
copy earlier messages do not count twice. Nothing from the logs is kept except
counts and dates per known key, and names that pass a strict pattern."""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .discovery import World

COMMAND_RE = re.compile(r"<command-name>(.*?)</command-name>")
UNMATCHED_NAME_RE = re.compile(r"^/?[A-Za-z0-9._:-]{1,80}$", re.ASCII)
PREFILTER = ("<command-name>", '"Skill"', '"Agent"', '"Task"')


@dataclass
class UsageResult:
    counts: dict[str, tuple[int, str | None]] = field(default_factory=dict)
    unmatched: list[dict] = field(default_factory=list)
    since: str | None = None
    sessions: int = 0
    skipped: int = 0


def _day(ts) -> str | None:
    """ISO 8601 timestamp to the local date."""
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return None


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return []


def count_usage(world: World, logs: Path) -> UsageResult:
    entries = world.entries
    counts: dict[str, list] = {}
    unmatched: dict[str, list] = {}
    seen: set[str] = set()
    result = UsageResult()
    earliest: str | None = None

    def hit(key: str | None, raw: str, day: str | None) -> None:
        if key is None:
            if not UNMATCHED_NAME_RE.match(raw):
                return              # free text never leaves the logs
            slot = unmatched.setdefault(raw, [0, None])
        else:
            slot = counts.setdefault(key, [0, None])
        slot[0] += 1
        if day and (slot[1] is None or day > slot[1]):
            slot[1] = day

    def command_key(name: str) -> str | None:
        name = name[1:] if name.startswith("/") else name
        if name in entries and entries[name].kind in ("command", "skill"):
            return name
        if ":" not in name and f"builtin:{name}" in entries:
            return f"builtin:{name}"
        return None

    files = sorted(logs.glob("*/*.jsonl")) if logs.is_dir() else []
    for path in files:
        result.sessions += 1
        first_day = None
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if first_day is None and '"timestamp"' in line:
                    m = re.search(r'"timestamp"\s*:\s*"([^"]+)"', line)
                    first_day = _day(m.group(1)) if m else None
                if not any(s in line for s in PREFILTER):
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    result.skipped += 1
                    continue
                if not isinstance(obj, dict):
                    continue
                uid = obj.get("uuid")
                if isinstance(uid, str):
                    if uid in seen:
                        continue
                    seen.add(uid)
                day = _day(obj.get("timestamp"))
                if day and (earliest is None or day < earliest):
                    earliest = day
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                if obj.get("type") == "user":
                    for text in _texts(msg.get("content")):
                        for raw in COMMAND_RE.findall(text):
                            raw = raw.strip()
                            hit(command_key(raw), raw, day)
                elif obj.get("type") == "assistant" and isinstance(msg.get("content"), list):
                    for part in msg["content"]:
                        if not isinstance(part, dict) or part.get("type") != "tool_use":
                            continue
                        inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                        if part.get("name") == "Skill" and isinstance(inp.get("skill"), str):
                            hit(command_key(inp["skill"]), inp["skill"], day)
                        elif part.get("name") in ("Agent", "Task") and isinstance(inp.get("subagent_type"), str):
                            v = inp["subagent_type"]
                            hit(f"agent:{v}" if f"agent:{v}" in entries else None, v, day)
        if first_day and (earliest is None or first_day < earliest):
            earliest = first_day

    result.counts = {k: (v[0], v[1]) for k, v in counts.items()}
    result.unmatched = [{"name": k, "count": v[0], "last": v[1]}
                        for k, v in sorted(unmatched.items(), key=lambda kv: (-kv[1][0], kv[0]))]
    result.since = earliest
    return result
