"""Command line: build, diff, mark-published, check, fingerprint."""
import argparse
import sys

from .config import ConfigError, load_config

DESCRIPTION = """\
skill-map - an overview page of the skills, commands, plugins and agents Claude Code can use

  skill-map build [--out DIR]   write inventory.json, wortlaut.json, index.html and skill-map.html
  skill-map diff [--texts]      what is new, removed or changed since the last publish
  skill-map mark-published      after a successful publish: remember this build
  skill-map check               session start hook: one line when the set changed, else nothing
  skill-map fingerprint         print the current fingerprint and the set it is computed from

Config: ~/.config/skill-map/skill-map.conf (TOML, optional; see example.conf)
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit 2 with the usage on stderr
        self.print_usage(sys.stderr)
        print(f"skill-map: {message}", file=sys.stderr)
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="skill-map", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    b = sub.add_parser("build", help="write the data and the page")
    b.add_argument("--out", help="output folder (default: <state>/build)")
    d = sub.add_parser("diff", help="compare the build with the last publish")
    d.add_argument("--texts", action="store_true", help="print the new and changed texts in full")
    sub.add_parser("mark-published", help="remember the build as published")
    sub.add_parser("check", help="hook mode: one line when the set changed")
    sub.add_parser("fingerprint", help="print the fingerprint and its set")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"skill-map: {e}", file=sys.stderr)
        return 2
    print(f"skill-map: {args.command} is not implemented yet", file=sys.stderr)  # replaced task by task
    del cfg
    return 1
