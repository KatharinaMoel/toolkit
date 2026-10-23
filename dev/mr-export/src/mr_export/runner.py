"""Every external command goes through here: shown with a one-line explanation,
then run. Explanations go to stderr, so stdout stays free for results.

Style: '* <what happens>', then '  > <command>', then '  = <result>'; notes '  ! ...'.
"""
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, TextIO

# glab switches a request to POST as soon as a field or body is given; a method
# flag could name any verb. None of these may ever reach glab from this tool.
FORBIDDEN_GLAB_ARGS = ("-f", "--raw-field", "-F", "--field", "--input", "--form", "-X", "--method")


def assert_read_only(args: list[str]) -> None:
    bad = [a for a in args if a in FORBIDDEN_GLAB_ARGS]
    if bad:
        raise ValueError(f"refusing glab arguments that could change data: {bad}")


class CommandError(Exception):
    """An external command failed; the message carries its stderr."""


class Console:
    def __init__(self, err: TextIO | None = None, quiet: bool = False):
        self.err = err or sys.stderr
        self.quiet = quiet   # only notes (problems) are printed, e.g. for a timer's journal

    def step(self, explanation: str, command: list[str] | None = None) -> None:
        if self.quiet:
            return
        print(f"\n* {explanation}", file=self.err)
        if command:
            print(f"  > {shlex.join(command)}", file=self.err)

    def result(self, text: str) -> None:
        if self.quiet:
            return
        print(f"  = {text}", file=self.err)

    def note(self, text: str) -> None:
        print(f"  ! {text}", file=self.err)

    def line(self, text: str = "") -> None:
        if self.quiet:
            return
        print(text, file=self.err)


Run = Callable[..., subprocess.CompletedProcess]


class Runner:
    """Runs git and glab in one repository folder. `run` is injectable for tests."""

    def __init__(self, repo: Path, console: Console, run: Run = subprocess.run, timeout: int = 180):
        self.repo = repo
        self.console = console
        self._run = run
        self.timeout = timeout

    def git(self, args: list[str], explanation: str | None) -> str:
        cmd = ["git", "-C", str(self.repo), *args]
        if explanation:
            self.console.step(explanation, cmd)
        # Diffs may hold files in other encodings; undecodable bytes become U+FFFD.
        return self._exec(cmd).decode(errors="replace").strip()

    def glab_get(self, endpoint: str, explanation: str | None, *, paginate: bool = False,
                 ndjson: bool = False) -> bytes:
        """GET one API endpoint. With explanation=None the call runs without being
        shown - only for repeats of a call that was shown once just before."""
        if not endpoint.startswith("projects/") or any(c.isspace() for c in endpoint):
            raise ValueError(f"unexpected endpoint: {endpoint!r}")
        args = ["glab", "api"]
        if paginate:
            args.append("--paginate")
        if ndjson:
            args += ["--output", "ndjson"]
        args.append(endpoint)
        assert_read_only(args)
        if explanation:
            self.console.step(explanation, args)
        return self._exec(args)

    def git_ok(self, args: list[str], explanation: str | None) -> bool:
        """For git commands that answer yes/no by exit code: 0 -> True, 1 -> False,
        anything else is an error."""
        cmd = ["git", "-C", str(self.repo), *args]
        if explanation:
            self.console.step(explanation, cmd)
        res = self._call(cmd)
        if res.returncode in (0, 1):
            return res.returncode == 0
        msg = (res.stderr or b"").decode(errors="replace").strip() or f"exit code {res.returncode}"
        raise CommandError(msg)

    def git_status(self, args: list[str], explanation: str | None) -> tuple[int, str]:
        """Exit code and output, for git commands where exit 1 is an answer, not an error."""
        cmd = ["git", "-C", str(self.repo), *args]
        if explanation:
            self.console.step(explanation, cmd)
        res = self._call(cmd)
        if res.returncode not in (0, 1):
            msg = (res.stderr or b"").decode(errors="replace").strip() or f"exit code {res.returncode}"
            raise CommandError(msg)
        return res.returncode, (res.stdout or b"").decode(errors="replace")

    def tool(self, args: list[str], explanation: str | None) -> str:
        """Any other local program (xdg-mime, flatpak, systemctl ...); errors raise."""
        if explanation:
            self.console.step(explanation, args)
        return self._exec(args).decode(errors="replace").strip()

    def tool_ok(self, args: list[str], explanation: str | None) -> bool:
        """A local program asked a yes/no question by exit code (0 = yes)."""
        if explanation:
            self.console.step(explanation, args)
        return self._call(args).returncode == 0

    def _call(self, cmd: list[str]) -> subprocess.CompletedProcess:
        try:
            return self._run(cmd, cwd=self.repo, capture_output=True, timeout=self.timeout)
        except FileNotFoundError as e:
            raise CommandError(f"{cmd[0]} is not installed") from e
        except subprocess.TimeoutExpired as e:
            raise CommandError(f"no answer within {self.timeout} s: {shlex.join(cmd)}") from e

    def _exec(self, cmd: list[str]) -> bytes:
        res = self._call(cmd)
        if res.returncode != 0:
            msg = (res.stderr or b"").decode(errors="replace").strip() or f"exit code {res.returncode}"
            raise CommandError(msg)
        return res.stdout
