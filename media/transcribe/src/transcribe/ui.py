"""Terminal output in the toolkit's explain-then-run style.

  * <explanation>        what happens next and why
    > <command>          the exact command (or request) that runs
    = <result>           what came out
    ! <warning>          something to notice

Explanations go to stderr, results meant for scripts to stdout.
"""

import os
import shlex
import sys


class Abort(Exception):
    """A deliberate stop with a message for the user (exit code 1)."""


def _colors():
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        return "\033[1;36m", "\033[2m", "\033[1;33m", "\033[1;31m", "\033[0m"
    return "", "", "", "", ""


# C0 (except tab and newline), DEL and C1 control characters: feed text could
# otherwise carry ANSI/OSC escapes that rewrite the screen or the clipboard.
_CONTROL = dict.fromkeys(c for c in [*range(0x00, 0x20), *range(0x7F, 0xA0)] if c not in (0x09, 0x0A))


def clean(text):
    return str(text).translate(_CONTROL)


def _err(text):
    sys.stdout.flush()  # keep results and explanations in order when both go to one log
    print(text, file=sys.stderr, flush=True)


def quote(cmd):
    """Show an argv list as a copy-pasteable shell line."""
    return cmd if isinstance(cmd, str) else shlex.join(str(c) for c in cmd)


class Terminal:
    def step(self, explanation, cmd=None):
        explanation = clean(explanation)
        cmd = None if cmd is None else clean(quote(cmd))
        expl, dim, _, _, off = _colors()
        _err(f"\n{expl}* {explanation}{off}")
        if cmd is not None:
            _err(f"{dim}  > {quote(cmd)}{off}")

    def result(self, text):
        _err(f"  = {clean(text)}")

    def warn(self, text):
        _, _, note, _, off = _colors()
        _err(f"{note}  ! {clean(text)}{off}")

    def note(self, text):
        _, _, note, _, off = _colors()
        _err(f"\n{note}* {clean(text)}{off}")

    def error(self, text):
        _, _, _, err, off = _colors()
        _err(f"\n{err}Fehler: {clean(text)}{off}")


class Silent(Terminal):
    """For tests: swallow all output."""

    def step(self, explanation, cmd=None):
        pass

    def result(self, text):
        pass

    def warn(self, text):
        pass

    def note(self, text):
        pass
