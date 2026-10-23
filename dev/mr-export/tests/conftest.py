"""Test setup: the package under src/ is importable, every test runs in a throwaway
HOME, any network access fails the test, and glab/git are replaced by a fake."""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LAUNCHER = Path(__file__).resolve().parent.parent / "mr-export"

UPLOAD_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("mr-export must never open a network connection itself")
    monkeypatch.setattr(socket, "socket", refuse)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    return h


def mr(iid, **over):
    data = {
        "iid": iid, "title": f"FIX: thing {iid}", "draft": False, "state": "opened",
        "source_branch": f"fix/thing-{iid}", "target_branch": "dev",
        "author": {"username": "alice"}, "assignees": [], "reviewers": [{"username": "bob"}],
        "labels": ["Review: easy"], "head_pipeline": {"status": "success"},
        "web_url": f"https://git.example.org/team/app/-/merge_requests/{iid}",
        "created_at": "2026-10-01T08:00:00.000Z", "updated_at": "2026-10-02T09:30:00.000Z",
        "description": "Plain text.", "sha": "a" * 40,
    }
    data.update(over)
    return data


def note(body, **over):
    n = {"body": body, "author": {"username": "bob"}, "created_at": "2026-10-02T10:00:00.000Z",
         "system": False, "resolvable": False, "resolved": False}
    n.update(over)
    return n


class FakeGitLab:
    """Stands in for subprocess.run: answers git and glab calls from a table and
    records every command. Endpoints not in the table fail like glab does."""

    def __init__(self, mrs, discussions=None, approvals=None, uploads=None, repo="/work/app"):
        self.calls: list[list[str]] = []
        self.mrs = mrs
        self.discussions = discussions or {}
        self.approvals = approvals or {}
        self.uploads = uploads or {}
        self.repo = repo
        self.fail: set[str] = set()
        self.members = [{"username": "alice", "access_level": 40}, {"username": "bob", "access_level": 30}]

    def answer(self, cmd):
        if cmd[0] == "git":
            if "rev-parse" in cmd:
                return self.repo + "\n"
            if "get-url" in cmd:
                return "ssh://git.example.org/team/app.git\n"
        assert cmd[:2] == ["glab", "api"], cmd
        ep = cmd[-1]
        if ep in self.fail:
            return None
        if ep.startswith("projects/:id/members/all"):
            return "".join(json.dumps(m) + "\n" for m in self.members)
        if ep == "projects/:id":
            return json.dumps({"path_with_namespace": "team/app", "web_url": "https://git.example.org/team/app"})
        if ep.startswith("projects/:id/merge_requests?"):
            return "".join(json.dumps(m) + "\n" for m in self.mrs)
        if ep.startswith("projects/:id/uploads/"):
            return self.uploads.get(ep.split("/", 3)[3], None)
        parts = ep.split("?")[0].split("/")
        iid = int(parts[3])
        if len(parts) == 4:
            return json.dumps(next(m for m in self.mrs if m["iid"] == iid))
        if parts[4] == "discussions":
            return "".join(json.dumps(d) + "\n" for d in self.discussions.get(iid, []))
        if parts[4] == "approvals":
            return json.dumps(self.approvals.get(iid, {"approvals_required": 1, "approvals_left": 1,
                                                       "approved_by": []}))
        return None

    def __call__(self, cmd, cwd=None, capture_output=True, timeout=None):
        self.calls.append(list(cmd))
        out = self.answer(cmd)
        if out is None:
            return subprocess.CompletedProcess(cmd, 1, b"", b"404 Not Found")
        return subprocess.CompletedProcess(cmd, 0, out if isinstance(out, bytes) else out.encode(), b"")


@pytest.fixture
def gitlab():
    discussions = {
        2: [
            {"notes": [note("Please rename ![shot](/uploads/%s/screen%%20one.png)" % UPLOAD_ID,
                            resolvable=True, resolved=False,
                            position={"new_path": "app/views.py", "new_line": 42})]},
            {"notes": [note("assigned to @bob", system=True)]},
        ],
    }
    return FakeGitLab([mr(1), mr(2, description="See ![a](/uploads/%s/a.png)" % UPLOAD_ID)],
                      discussions=discussions,
                      approvals={1: {"approvals_required": 1, "approvals_left": 0, "approved": True,
                                     "approved_by": [{"user": {"username": "carol"}}]}},
                      uploads={f"{UPLOAD_ID}/a.png": b"PNG-A", f"{UPLOAD_ID}/screen%20one.png": b"PNG-B"})


@pytest.fixture(autouse=True)
def no_git_state(monkeypatch, request):
    """fetch() reads Git state through collect_git_state; tests that run fetch against the
    fake GitLab get a stub that records its call. Tests marked 'real_git' keep the real one."""
    if request.node.get_closest_marker("real_git"):
        return None
    import mr_export.fetch as fetch_mod
    calls = []

    def stub(runner, console, mrs, emergency, snap):
        calls.append({"mrs": [m.iid for m in mrs], "emergency": emergency, "snap": snap})
        return []
    monkeypatch.setattr(fetch_mod, "collect_git_state", stub)
    return calls


def pytest_configure(config):
    config.addinivalue_line("markers", "real_git: run fetch with the real Git state collector")
