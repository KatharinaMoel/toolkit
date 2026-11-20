"""Why Git over SSH failed, and the HTTPS way out: probes answered by a fake, no network."""
import json
import subprocess
from io import StringIO

import pytest

from mr_export import reach
from mr_export.runner import Console, Runner

HOST = "git.example.org"
NO_ROUTE = "ssh: connect to host git.example.org port 22: No route to host"
PERMISSION = "git@git.example.org: Permission denied (publickey)."
INTERNAL = "remote:\nremote: ========\nremote: Internal API unreachable"
DIAL = "ERROR: dial tcp: lookup git.example.org: no such host"


class FakeNet:
    """Stands in for subprocess.run. SSH (in git or the probe) answers with `ssh`, the
    API probe with `glab` (None = success), the internet probe with `curl` (exit code).
    git with 'insteadOf' in its arguments is the HTTPS way and answers with `https_rc`."""

    def __init__(self, ssh=NO_ROUTE, glab=None, curl=6, https_rc=0,
                 url=f"git@{HOST}:team/app.git"):
        self.ssh, self.glab, self.curl, self.https_rc, self.url = ssh, glab, curl, https_rc, url
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, cmd, cwd=None, capture_output=True, timeout=None, env=None):
        self.calls.append((list(cmd), env))

        def done(code, out="", err=""):
            return subprocess.CompletedProcess(cmd, code, out.encode(), err.encode())
        if cmd[0] == "git":
            if "get-url" in cmd:
                return done(0, self.url + "\n")
            if any("insteadOf" in a for a in cmd):
                if self.https_rc:
                    return done(self.https_rc, err="fatal: Authentication failed")
                if "ls-remote" in cmd:
                    return done(0, "abc\trefs/heads/dev\n")
                return done(0)
            return done(128, err=self.ssh + "\nfatal: Could not read from remote repository.")
        if cmd[:2] == ["timeout", "10"] and "glab" in cmd:
            return done(0, '{"version":"18.0.0"}') if self.glab is None else done(1, err=self.glab)
        if cmd[:2] == ["timeout", "10"]:
            return done(255, err=self.ssh)
        if cmd[0] == "curl":
            return done(self.curl)
        raise AssertionError(cmd)

    def ran(self, word):
        return [c for c, _ in self.calls if word in c]

    def https_calls(self):
        return [(c, env) for c, env in self.calls if any("insteadOf" in a for a in c)]


def runner_for(net, tmp_path):
    return Runner(tmp_path, Console(StringIO()), run=net)


@pytest.mark.parametrize("code,out,kind", [
    (0, '{"version":"18"}', "ok"),
    (1, "glab: 502 Bad Gateway (HTTP 502)", "server-error"),
    (1, "HTTP 503 Service Unavailable", "server-error"),
    (1, 'Get "https://h/api/v4/version": dial tcp 1.2.3.4:443: i/o timeout', "no-connection"),
    (1, "connect: no route to host", "no-connection"),
    (1, "connect: Connection refused", "no-connection"),
    (124, "", "no-connection"),
    (1, "HTTP 401 Unauthorized", "error"),
    (127, "timeout: failed to run command 'glab': No such file or directory", "error"),
])
def test_classify_https(code, out, kind):
    assert reach.classify_https(code, out) == kind


@pytest.mark.parametrize("out,kind", [
    ("Welcome to GitLab, @someone!", "ok"),
    (INTERNAL, "server-error"),
    (NO_ROUTE, "no-connection"),
    ("ssh: connect to host h port 22: Connection timed out", "no-connection"),
    ("ssh: connect to host h port 22: Network is unreachable", "no-connection"),
    ("ssh: Could not resolve hostname h: Name or service not known", "no-connection"),
    (PERMISSION, "error"),
])
def test_classify_ssh(out, kind):
    assert reach.classify_ssh(255, out) == kind


def test_ssh_timeout_counts_as_no_connection():
    assert reach.classify_ssh(124, "") == "no-connection"


@pytest.mark.parametrize("ssh,https,state", [
    ("ok", "ok", "ok"),
    ("no-connection", "ok", "https-only"),
    ("error", "ok", "ssh-key"),
    ("server-error", "ok", "gitlab-down"),
    ("no-connection", "server-error", "gitlab-down"),
    ("no-connection", "no-connection", "both-no-connection"),
    ("no-connection", "error", "unknown"),
    ("ok", "no-connection", "unknown"),
])
def test_decide(ssh, https, state):
    assert reach.decide(ssh, https) == state


@pytest.mark.parametrize("url,host", [
    ("git@git.example.org:team/app.git", HOST),
    ("ssh://git@git.example.org/team/app.git", HOST),
    ("ssh://git@git.example.org:2222/team/app.git", HOST),
    ("ssh://git.example.org/team/app.git", HOST),
    ("https://git.example.org/team/app.git", None),
    ("/srv/git/app.git", None),
    ("", None),
    ("git@bad;host:app.git", None),
])
def test_ssh_host(url, host):
    assert reach.ssh_host(url) == host


def test_diagnose_https_only_probes_the_remote_host(tmp_path):
    net = FakeNet(ssh=NO_ROUTE, glab=None)
    found = reach.diagnose(runner_for(net, tmp_path), f"git@{HOST}:team/app.git")
    assert (found.state, found.ssh, found.https) == ("https-only", "no-connection", "ok")
    assert found.https_way_out
    assert found.message == ("GitLab nur über HTTPS erreichbar (SSH Port 22 zu, vermutlich VPN) – "
                             "weiche auf HTTPS aus (Fall https-only: SSH no-connection, HTTPS ok)")
    assert ["timeout", "10", "glab", "api", "--hostname", HOST, "version"] in [c for c, _ in net.calls]
    assert ["timeout", "10", "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            f"git@{HOST}"] in [c for c, _ in net.calls]
    assert not net.ran("curl")


def test_diagnose_uses_git_ssh_command(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -p 2")
    net = FakeNet()
    reach.diagnose(runner_for(net, tmp_path), f"git@{HOST}:team/app.git")
    ssh_call = next(c for c, _ in net.calls if f"git@{HOST}" in c)
    assert ssh_call[:7] == ["timeout", "10", "ssh", "-o", "BatchMode=yes", "-p", "2"]


@pytest.mark.parametrize("ssh,glab,curl,state", [
    (PERMISSION, None, 6, "ssh-key"),
    (INTERNAL, None, 6, "gitlab-down"),
    (NO_ROUTE, "glab: 502 Bad Gateway (HTTP 502)", 6, "gitlab-down"),
    ("ssh: Could not resolve hostname x", DIAL, 6, "offline"),
    (NO_ROUTE, DIAL, 0, "fu-unreachable"),
    (NO_ROUTE, "HTTP 401 Unauthorized", 0, "unknown"),
])
def test_diagnose_cases(tmp_path, ssh, glab, curl, state):
    net = FakeNet(ssh=ssh, glab=glab, curl=curl)
    found = reach.diagnose(runner_for(net, tmp_path), f"git@{HOST}:team/app.git")
    assert found.state == state
    assert f"(Fall {state}:" in found.message
    assert found.https_way_out == (state == "ssh-key")
    assert bool(net.ran("curl")) == (state in ("offline", "fu-unreachable"))


def test_diagnose_without_ssh_url_probes_nothing(tmp_path):
    net = FakeNet()
    found = reach.diagnose(runner_for(net, tmp_path), "/srv/git/app.git")
    assert found.state == "unknown" and not found.https_way_out
    assert "(Fall unknown)" in found.message
    assert net.calls == []


def collect(net, tmp_path):
    from mr_export.fetch import collect_git_state
    snap = tmp_path / "snap"
    (snap / "mr").mkdir(parents=True)
    runner = runner_for(net, tmp_path)
    console_out = StringIO()
    failures = collect_git_state(runner, Console(console_out), [], {}, snap)
    return failures, snap, runner, console_out.getvalue()


@pytest.mark.real_git
@pytest.mark.parametrize("ssh", [NO_ROUTE, PERMISSION])
def test_collect_takes_the_https_way_out(tmp_path, ssh):
    net = FakeNet(ssh=ssh, glab=None)
    failures, snap, runner, out = collect(net, tmp_path)
    assert failures == []
    assert json.loads((snap / "git.json").read_text()) == {}
    https = net.https_calls()
    assert [c[c.index("ls-remote") if "ls-remote" in c else c.index("fetch")] for c, _ in https] \
        == ["ls-remote", "fetch"]
    for cmd, env in https:
        assert "credential.helper=!glab auth git-credential" in cmd
        assert f"url.https://{HOST}/.insteadOf=git@{HOST}:" in cmd
        assert f"url.https://{HOST}/.insteadOf=ssh://git@{HOST}/" in cmd
        assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert runner.git_config == [] and runner.git_env == {}
    assert "weiche auf HTTPS aus" in out and "Read over HTTPS." in out


@pytest.mark.real_git
@pytest.mark.parametrize("ssh,glab,curl,state", [
    (INTERNAL, None, 6, "gitlab-down"),
    ("ssh: Could not resolve hostname x", DIAL, 6, "offline"),
    (NO_ROUTE, DIAL, 0, "fu-unreachable"),
])
def test_collect_has_no_way_out_when_https_cannot_help(tmp_path, ssh, glab, curl, state):
    net = FakeNet(ssh=ssh, glab=glab, curl=curl)
    failures, snap, _, out = collect(net, tmp_path)
    assert len(failures) == 1 and f"(Fall {state}:" in failures[0]
    assert net.https_calls() == []
    assert not (snap / "git.json").exists()
    assert f"(Fall {state}:" in out


@pytest.mark.real_git
def test_collect_reports_when_https_fails_too(tmp_path):
    net = FakeNet(ssh=NO_ROUTE, glab=None, https_rc=128)
    failures, snap, runner, out = collect(net, tmp_path)
    assert len(failures) == 1 and "Fall https-only" in failures[0] and "HTTPS: fatal" in failures[0]
    assert not (snap / "git.json").exists()
    assert runner.git_config == [] and runner.git_env == {}
    assert "Git over HTTPS failed too" in out
