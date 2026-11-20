"""Why did Git over SSH fail? Runs only after a failed SSH call: probes SSH and the
GitLab API over HTTPS (and, when both have no connection, the internet), names the
case, and says whether trying HTTPS once is worth it. The way out over HTTPS is a set
of 'git -c' settings for single calls; no config file is changed."""
import os
import re
import shlex
from dataclasses import dataclass

from .runner import Runner

MESSAGES = {
    "ok": "GitLab erreichbar",
    "https-only": "GitLab nur über HTTPS erreichbar (SSH Port 22 zu, vermutlich VPN) – weiche auf HTTPS aus",
    "gitlab-down": "GitLab selbst gestört (Serverfehler) – später erneut",
    "fu-unreachable": "GitLab nicht erreichbar, Internet geht – FU-VPN einschalten?",
    "offline": "Kein Netz",
    "ssh-key": "SSH-Anmeldung abgelehnt (Schlüssel?) – weiche auf HTTPS aus",
    "unknown": "Ursache unklar",
}
HTTPS_WAY_OUT = {"https-only", "ssh-key"}

_HTTPS_SERVER = re.compile(r"(^|[^0-9])50[0234]([^0-9]|$)|HTTP 5")
_HTTPS_NO_CONN = re.compile(r"no route to host|i/o timeout|timeout|connection refused|"
                            r"network is unreachable|dial tcp", re.IGNORECASE)
_SSH_NO_CONN = re.compile(r"no route to host|timed out|connection refused|network is unreachable|"
                          r"could not resolve hostname", re.IGNORECASE)
_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


@dataclass
class Reach:
    state: str
    host: str | None
    ssh: str = "-"
    https: str = "-"

    @property
    def https_way_out(self) -> bool:
        return self.state in HTTPS_WAY_OUT and self.host is not None

    @property
    def message(self) -> str:
        if self.host is None:
            return f"{MESSAGES['unknown']} - die Remote-URL ist keine SSH-URL, nichts zu prüfen (Fall unknown)"
        return f"{MESSAGES[self.state]} (Fall {self.state}: SSH {self.ssh}, HTTPS {self.https})"


def ssh_host(url: str) -> str | None:
    """Host of an SSH remote URL (git@host:path, ssh://[user@]host[:port]/path), else None."""
    if url.startswith("ssh://"):
        host = url[len("ssh://"):].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    elif "://" in url or "@" not in url or ":" not in url:
        return None
    else:
        host = url.split("@", 1)[1].split(":", 1)[0]
    return host if host and _HOST.match(host) else None


def classify_https(code: int, output: str) -> str:
    if code == 0:
        return "ok"
    if code == 127:   # glab (or timeout) not installed - its message names 'timeout'
        return "error"
    if code == 124:   # 'timeout' ends the probe silently
        output += " timeout"
    if _HTTPS_SERVER.search(output):
        return "server-error"
    if _HTTPS_NO_CONN.search(output):
        return "no-connection"
    return "error"


def classify_ssh(code: int, output: str) -> str:
    if code == 124:
        output += " timed out"
    if "Welcome to GitLab" in output:
        return "ok"
    if "Internal API unreachable" in output:
        return "server-error"
    if _SSH_NO_CONN.search(output):
        return "no-connection"
    return "error"


def decide(ssh: str, https: str) -> str:
    """The case from both probes; 'no-connection' on both sides needs the internet probe
    and comes back as 'both-no-connection'."""
    if "server-error" in (ssh, https):
        return "gitlab-down"
    if ssh == "ok" and https == "ok":
        return "ok"
    if https == "ok" and ssh == "no-connection":
        return "https-only"
    if https == "ok" and ssh == "error":
        return "ssh-key"
    if https == "no-connection" and ssh == "no-connection":
        return "both-no-connection"
    return "unknown"


def diagnose(runner: Runner, remote_url: str) -> Reach:
    host = ssh_host(remote_url)
    if host is None:
        return Reach("unknown", None)
    code, out = runner.probe(["timeout", "10", "glab", "api", "--hostname", host, "version"],
                             f"HTTPS-Probe: antwortet die GitLab-API von {host}?")
    https = classify_https(code, out)
    # The same SSH command line Git uses, so the probe checks what the fetch used.
    ssh_cmd = shlex.split(os.environ.get("GIT_SSH_COMMAND") or "ssh")
    code, out = runner.probe(["timeout", "10", *ssh_cmd, "-T", "-o", "BatchMode=yes",
                              "-o", "ConnectTimeout=5", f"git@{host}"],
                             f"SSH-Probe: lässt {host} uns per SSH herein?")
    ssh = classify_ssh(code, out)
    state = decide(ssh, https)
    if state == "both-no-connection":
        code, _ = runner.probe(["curl", "-sS", "-o", "/dev/null", "--max-time", "5", "https://github.com"],
                               "Internet-Probe: geht überhaupt etwas raus?")
        state = "fu-unreachable" if code == 0 else "offline"
    return Reach(state, host, ssh, https)


def https_git_config(host: str) -> list[str]:
    """'git -c' settings that send one call over HTTPS with glab as credential helper."""
    return ["-c", "credential.helper=",
            "-c", "credential.helper=!glab auth git-credential",
            "-c", f"url.https://{host}/.insteadOf=git@{host}:",
            "-c", f"url.https://{host}/.insteadOf=ssh://git@{host}/"]


HTTPS_ENV = {"GIT_TERMINAL_PROMPT": "0"}
