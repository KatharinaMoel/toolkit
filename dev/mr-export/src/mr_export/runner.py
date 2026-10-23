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
    def __init__(self, err: TextIO | None = None):
        self.err = err or sys.stderr

    def step(self, explanation: str, command: list[str] | None = None) -> None:
        print(f"\n* {explanation}", file=self.err)
        if command:
            print(f"  > {shlex.join(command)}", file=self.err)

    def result(self, text: str) -> None:
        print(f"  = {text}", file=self.err)

    def note(self, text: str) -> None:
        print(f"  ! {text}", file=self.err)

    def line(self, text: str = "") -> None:
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
        return self._exec(cmd).decode().strip()

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

    def _exec(self, cmd: list[str]) -> bytes:
        try:
            res = self._run(cmd, cwd=self.repo, capture_output=True, timeout=self.timeout)
        except FileNotFoundError as e:
            raise CommandError(f"{cmd[0]} is not installed") from e
        except subprocess.TimeoutExpired as e:
            raise CommandError(f"no answer within {self.timeout} s: {shlex.join(cmd)}") from e
        if res.returncode != 0:
            msg = (res.stderr or b"").decode(errors="replace").strip() or f"exit code {res.returncode}"
            raise CommandError(msg)
        return res.stdout
