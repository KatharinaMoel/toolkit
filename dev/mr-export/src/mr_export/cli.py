"""Command line: `mr-export fetch` reads merge requests into a new snapshot and renders
it; `mr-export render` renders an existing snapshot again."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import render as render_mod
from . import snapshot
from .config import STATES, ConfigError, default_path, load_config
from .fetch import fetch
from .runner import CommandError, Console, Runner

USAGE = """mr-export - GitLab merge requests as a local snapshot with an offline overview

  mr-export fetch [--state opened|merged|closed|locked|all] [--no-images] [--yes] [--repo DIR]
        Read the merge requests of the repository you are in (via glab, GET only)
        into <out_dir>/<repo>/<YYYY-MM-DD_HHMM>/, then write index.html there.
  mr-export render [SNAPSHOT_DIR] [--repo DIR]
        Write the HTML pages again; without a folder: the newest snapshot of the repo.

Every external command is shown with a one-line explanation before it runs.
Config (optional, TOML): ~/.config/mr-export/mr-export.conf - keys out_dir, state, images.
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mr-export", usage=USAGE, add_help=False)
    p.add_argument("-h", "--help", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    f = sub.add_parser("fetch", add_help=False)
    f.add_argument("--state", choices=STATES)
    f.add_argument("--no-images", action="store_true")
    f.add_argument("--no-render", action="store_true")
    f.add_argument("--yes", action="store_true")
    f.add_argument("--repo", type=Path)
    r = sub.add_parser("render", add_help=False)
    r.add_argument("snapshot", nargs="?", type=Path)
    r.add_argument("--repo", type=Path)
    return p


def confirm(console: Console, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        console.note("No terminal to ask in - run again with --yes to go ahead without asking.")
        return False
    try:
        print("\nContinue? [Y/n] ", end="", file=sys.stderr, flush=True)   # stdout is only for the result
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in ("", "y", "yes", "j", "ja")


def repo_root(runner: Runner) -> Path:
    return Path(runner.git(["rev-parse", "--show-toplevel"], "Find the repository this runs in"))


def cmd_fetch(args, console: Console) -> int:
    cfg, cfg_path = load_config()
    state = args.state or cfg.state
    images = cfg.images and not args.no_images
    runner = Runner((args.repo or Path.cwd()).resolve(), console)
    top = repo_root(runner)
    console.result(str(top))
    origin = runner.git(["remote", "get-url", "origin"], "Read where the remote 'origin' points")
    console.result(origin)
    runner.repo = top
    root = cfg.out_dir / top.name

    def src(flag: bool) -> str:
        return "command line" if flag else (f"config {cfg_path}" if cfg_path else "default")

    console.line("\n── mr-export fetch ─────────────────────────────")
    console.line(f"  From:    the GitLab project behind {origin}")
    console.line("           (glab picks host and project from this repository; login: glab auth status)")
    console.line(f"  What:    merge requests with state '{state}' ({src(bool(args.state))}),")
    console.line("           each with threads, approvals and head pipeline"
                 + (", plus uploaded images" if images else "; no images (--no-images or config)"))
    console.line(f"  To:      {root}/<date_time>/  (out_dir: {src(False)}; a new folder each run)")
    console.line("  GitLab:  read only - every call is a GET via 'glab api'; nothing there changes")
    console.line("────────────────────────────────────────────────")
    if not confirm(console, args.yes):
        console.line("\nStopped. Nothing was read and nothing was written.")
        return 1

    result = fetch(runner, console, root, state, images, datetime.now())
    console.step(f"Write the overview pages into {result.path}")
    index = render_mod.render(snapshot.load(result.path)) if not args.no_render else None
    if index:
        console.result(str(index))

    console.line("\n── Result ──────────────────────────────────────")
    console.line(f"  {result.count} merge requests, {result.notes} notes, {result.images} images")
    console.line(f"  Snapshot: {result.path}")
    if index:
        console.line(f"  Open:     xdg-open {index}")
    for f in result.failures:
        console.line(f"  ! {f}")
    if result.failures:
        console.line(f"  ! {len(result.failures)} item(s) missing - the overview says so at the top.")
    print(index or result.path)   # stdout: only the path, for scripts
    return 1 if result.failures else 0


def finished(p: Path) -> bool:
    """A snapshot folder whose read did not stop half-way (hand-made folders count)."""
    if not ((p / "mrs.ndjson").is_file() or (p / "mrs-list.ndjson").is_file()):
        return False
    meta = p / "meta.json"
    try:
        return not meta.is_file() or json.loads(meta.read_text(encoding="utf-8")).get("complete", True)
    except (OSError, json.JSONDecodeError):
        return False


def newest_snapshot(root: Path) -> Path | None:
    candidates = [p for p in root.iterdir() if p.is_dir() and finished(p)] if root.is_dir() else []
    return max(candidates, key=lambda p: p.name) if candidates else None


def cmd_render(args, console: Console) -> int:
    path = args.snapshot
    if path is None:
        cfg, _ = load_config()
        runner = Runner((args.repo or Path.cwd()).resolve(), console)
        top = repo_root(runner)
        root = cfg.out_dir / top.name
        path = newest_snapshot(root)
        if path is None:
            console.note(f"No snapshot under {root} - run 'mr-export fetch' first, or name a folder.")
            return 1
        console.step(f"Newest snapshot of {top.name}")
        console.result(str(path))
    snap = snapshot.load(path.resolve())
    console.step(f"Write index.html and one page per merge request into {snap.path}")
    index = render_mod.render(snap)
    console.result(f"{len(snap.mrs)} merge requests")
    console.line(f"\n  Open: xdg-open {index}")
    print(index)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:   # argparse already printed the reason to stderr
        return 2 if e.code else 0
    if args.help or not args.cmd:
        print(USAGE)
        print(f"Config file: {default_path()}")
        return 0 if args.help else 2
    console = Console()
    try:
        return cmd_fetch(args, console) if args.cmd == "fetch" else cmd_render(args, console)
    except ConfigError as e:
        print(f"Error in config: {e}", file=sys.stderr)
        return 2
    except (CommandError, FileNotFoundError) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
