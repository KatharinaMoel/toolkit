"""Command line: build, diff, mark-published, check, fingerprint."""
import argparse
import json
import sys
from pathlib import Path

from .build import build, fingerprint
from .config import ConfigError, load_config
from .discovery import DiscoveryError, discover
from .paths import state_dir
from .state import check_message, diff, mark_published

DESCRIPTION = """\
skill-map - an overview page of the skills, commands, plugins and agents Claude Code can use

  skill-map build [--out DIR]   write inventory.json, wortlaut.json, index.html and skill-map.html
  skill-map diff [--texts]      what is new, removed or changed since the last publish
  skill-map mark-published      after a successful publish: remember this build
  skill-map check               session start hook: one line when the set changed, else nothing
  skill-map fingerprint         print the current fingerprint and the set it is computed from

  --profile NAME                before the command: use [profiles.NAME] from the config and its
                                own state folder, for a second page (see README, Profiles)

Config: ~/.config/skill-map/skill-map.conf (TOML, optional; see example.conf)
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit 2 with the usage on stderr
        self.print_usage(sys.stderr)
        print(f"skill-map: {message}", file=sys.stderr)
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="skill-map", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", help="a [profiles.NAME] table from the config")
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
    if args.command == "check":
        if args.profile is not None:     # check always covers the default and every published profile
            print("skill-map: check takes no --profile; it reports every published profile", file=sys.stderr)
            return 2
        return _check()
    try:
        cfg = load_config(profile=args.profile)
    except ConfigError as e:
        print(f"skill-map: {e}", file=sys.stderr)
        return 2
    log = lambda line: print(line, file=sys.stderr)   # explain-then-run, on stderr
    try:
        if args.command == "build":
            out = Path(args.out) if args.out else state_dir(cfg.profile) / "build"
            build(cfg, out, log)
            return 0
        if args.command == "diff":
            return diff(args.texts, log, print, cfg.profile)
        if args.command == "mark-published":
            return mark_published(cfg, log)
        if args.command == "fingerprint":
            fp, rows = fingerprint(discover(cfg))
            print(fp)
            for row in rows:
                print("\t".join(row))
            return 0
    except DiscoveryError as e:
        print(f"skill-map: {e}", file=sys.stderr)
        return 1
    return 2


def _check() -> int:
    """Hook mode: one JSON line with a systemMessage, or nothing. Never fails the session
    start and never reads stdin (Claude Code passes hook JSON there; it is not needed).
    The default page always counts; a profile only once it was published."""
    title = "Skill-Landkarte"
    lines = []
    try:
        cfg = load_config()
        title = cfg.title
        lines.append(check_message(cfg))
        for name in sorted(cfg.profiles):
            if (state_dir(name) / "published" / "fingerprint.json").is_file():
                lines.append(check_message(load_config(profile=name)))
    except Exception as e:      # noqa: BLE001 - any error becomes one visible line, exit 0
        reason = str(e).splitlines()[0] if str(e) else type(e).__name__
        lines.append(f"{title}: Prüfung fehlgeschlagen ({reason[:160]})")
    message = "\n".join(line for line in lines if line)
    if message:
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0
