"""The fixture world: a made-up Claude Code setup under a throwaway HOME.

Names, ids and paths are invented; nothing here describes a real machine."""
import json
import os
from pathlib import Path

FAKE_ID = "00000000-1111-4222-8333-444444444444"
FAKE_PAIR = FAKE_ID + "_55555555-6666-4777-8888-999999999999"
MARK = "<!-- kios:generated | Quelle: {} | Nicht von Hand aendern - aendere die Quelle und fuehre `kios sync` aus. -->"


def put(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    return path


def skill(folder: Path, name: str, desc: str = "", body: str = "body\n") -> Path:
    head = f"---\nname: {name}\n" + (f"description: {desc}\n" if desc else "") + "---\n"
    return put(folder / "SKILL.md", head + body)


def plugin_json(root: Path, **meta) -> None:
    put(root / ".claude-plugin" / "plugin.json", json.dumps(meta))


CONFIG = """\
vault = "~/vault"
source_roots = ["~/kios"]
tools = ["~/tk/*/*"]
withhold_text = ["zeit"]
[[projects]]
path = "~/proj"
label = "Proj"
[[projects]]
path = "~/does-not-exist"
label = "Gone"
[builtins]
code-review = "Review des aktuellen Diffs"
[areas]
arbeit = "Arbeit"
"""


def make_world(home: Path, managed: Path) -> dict:
    """Build the whole fixture world; returns a few paths the tests need."""
    ch = home / ".claude"
    # personal commands (kios-generated ones carry the marker on line 4, 5)
    put(ch / "commands/k-start.md", "---\ndescription: Session starten\n---\n" + MARK.format("templates/k-start.md") + "\n")
    put(ch / "commands/rb-a.md", "---\ndescription: Runbook A ausführen\nargument-hint: x\n---\n"
        + MARK.format("40-runbooks/rb-a.md") + "\n")
    put(ch / "commands/rb-c.md", "---\ndescription: Vertraulicher Ablauf\n---\n" + MARK.format("40-runbooks/rb-c.md") + "\n")
    put(ch / "commands/gone.md", "---\ndescription: alt\n---\n" + MARK.format("templates/missing.md") + "\n")
    put(ch / "commands/plain.md", "---\ndescription: Ein einfacher Befehl\n---\nplain\n")
    put(ch / "commands/tricky.md", "---\ndescription: <img src=x onerror=alert(1)>\n---\nends early? </script><b>no</b>\n")
    put(ch / "commands/start.md", "personal start\n")
    put(ch / "commands/alpha.md", "alpha as a command\n")
    put(ch / "commands/sub/subcmd.md", "in a subfolder\n")
    # personal skills
    skill(ch / "skills/alpha", "alpha", "Alpha skill")
    skill(ch / "skills/zeit", "zeit", "Arbeitszeit", "private numbers\n")
    skill(ch / "skills/.trash/old", "old")
    skill(home / "elsewhere/linked skill", "linked", "Linked")
    (ch / "skills/linked").symlink_to(home / "elsewhere/linked skill")
    put(ch / "agents/helper.md", "---\nname: helper\ndescription: A personal agent\n---\n")
    # managed
    skill(managed / ".claude/skills/mgd", "mgd", "Managed skill")
    # installed plugins
    pc = ch / "plugins/cache"
    superp = pc / "mkt/superp/7.0.0"
    plugin_json(superp, name="superp", version="7.0.0", author={"name": "Jane Vendor", "email": "jane@example.invalid"},
                homepage="https://example.invalid/superp", repository="not a url")
    skill(superp / "skills/brainstorming", "brainstorming", "Ideas first")
    skill(superp / "skills/tdd", "tdd", "Tests first")
    stale = pc / "mkt/superp/6.0.0"
    plugin_json(stale, name="superp", version="6.0.0")
    skill(stale / "skills/oldskill", "oldskill")
    review = pc / "mkt/reviewkit/abc123def456"
    plugin_json(review, name="reviewkit", author="Review People")
    put(review / "agents/code-reviewer.md", "---\nname: code-reviewer\ndescription: Reviews code\n---\nagent body\n")
    put(review / "commands/review.md", "---\ndescription: Review now\n---\nreview\n")
    pyd = pc / "mkt/pydantic-ai/0.1.0"
    plugin_json(pyd, name="ai", version="0.1.0")
    skill(pyd / "skills/building-agents", "building-agents", "Build agents")
    empty = pc / "mkt/emptyplug/2.0.0"
    plugin_json(empty, name="emptyplug", author={"name": "Hook Maker"})
    off = pc / "mkt/offplug/1.0.0"
    plugin_json(off, name="offplug")
    skill(off / "skills/offskill", "offskill")

    def inst(path, version, when):
        return [{"scope": "user", "installPath": str(path), "version": version, "installedAt": when}]
    put(ch / "plugins/installed_plugins.json", json.dumps({"version": 2, "plugins": {
        "superp@mkt": inst(superp, "7.0.0", "2026-09-01T10:00:00.000Z"),
        "reviewkit@mkt": inst(review, "abc123def456", "2026-09-02T10:00:00.000Z"),
        "pydantic-ai@mkt": inst(pyd, "0.1.0", "2026-09-03T10:00:00.000Z"),
        "offplug@mkt": inst(off, "1.0.0", "2026-09-04T10:00:00.000Z"),
        "emptyplug@mkt": inst(empty, "2.0.0", "2026-09-05T10:00:00.000Z"),
    }}))
    put(ch / "settings.json", json.dumps({
        "enabledPlugins": {"offplug@mkt": False, "superp@mkt": True},
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": str(ch / "hooks/boundary.sh"),
                                         "statusMessage": "Startort prüfen"}]}],
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 " + str(ch / "hooks/stop.py")}]}],
        }}))
    # claude.ai skills and plugins
    sk = ch / "skills/synced" / FAKE_PAIR
    put(sk / "manifest.json", json.dumps({"skills": [{"name": "pdf"}]}))
    skill(sk / "pdf", "pdf", "PDF files")
    put(sk / ".bucket-x", "")
    ps = ch / "plugins/synced" / FAKE_PAIR
    put(ps / "manifest.json", json.dumps({"plugins": [{"name": "eng", "generation": 3}]}))
    plugin_json(ps / "eng", name="eng")
    skill(ps / "eng/skills/old-review", "old-review")
    plugin_json(ps / "eng~g3", name="eng", author={"name": "Anthropic"})
    skill(ps / "eng~g3/skills/code-review", "code-review", "Review a diff")
    put(ps / "eng~g3/.in_use", "")
    # vault runbooks and kios templates
    v = home / "vault/40-runbooks"
    put(v / "rb-a.md", "---\ntitle: Runbook A\ncommand: rb-a\nstatus: aktiv\ntags: [runbook, arbeit, git]\n---\n")
    put(v / "rb-b.md", "---\ntitle: Runbook B\ncommand: rb-b\nstatus: entwurf\ntags: [runbook]\n---\n")
    put(v / "rb-c.md", "---\ntitle: Runbook C\ncommand: rb-c\nstatus: aktiv\nclassification: sensitive\n---\n")
    put(v / "_guide.md", "---\ntitle: Guide\n---\n")
    put(home / "kios/templates/k-start.md", "template\n")
    # a project (shadowed start, own command and skill, a project hook)
    pr = home / "proj/.claude"
    put(pr / "commands/start.md", "project start\n")
    put(pr / "commands/projcmd.md", "---\ndescription: Projektbefehl\n---\n")
    skill(pr / "skills/projskill", "projskill", "Project skill")
    put(pr / "settings.json", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "~/proj/.claude/hooks/guard.sh"}]}]}}))
    # toolkit tools
    for area, name, title in (("dev", "wt", "wt — disposable git worktrees"),
                              ("ai", "show", "show — read a skill unchanged")):
        exe = put(home / "tk" / area / name / name, "#!/bin/sh\n")
        os.chmod(exe, 0o755)
        put(home / "tk" / area / name / "README.md", f"# {title}\n\ntext\n")
    put(home / "tk/dev/notatool/README.md", "# not a tool\n")
    return {"superp": superp, "review": review, "pyd": pyd, "synced_plugins": ps, "synced_skills": sk}
