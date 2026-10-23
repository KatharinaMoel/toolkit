"""Command line: `mr-export fetch` reads merge requests into a new snapshot and renders
it; `mr-export render` renders an existing snapshot again."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import render as render_mod
from . import browser, retention, schedule
from . import snapshot
from .config import STATES, ConfigError, default_path, load_config
from .fetch import FetchLocked, fetch
from .runner import CommandError, Console, Runner

USAGE = """mr-export - GitLab merge requests as a local snapshot with an offline overview

  mr-export fetch [--state opened|merged|closed|locked|all] [--no-images] [--yes] [--repo DIR]
        Read the merge requests of the repository you are in (via glab, GET only)
        into <out_dir>/<repo>/<YYYY-MM-DD_HHMM>/, then write index.html there.
  mr-export schedule --every 30min|1h|2h [--repo DIR] | --off | --status
        A systemd user timer that runs 'fetch --yes --quiet' for this repository while you
        are logged in; shows the unit files and asks first.
  mr-export open [--repo DIR]
        Open <out_dir>/<repo>/latest/index.html in the default browser; says how to fix a
        Flatpak browser that cannot see the folder.
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
    f.add_argument("--quiet", action="store_true")
    f.add_argument("--repo", type=Path)
    sc = sub.add_parser("schedule", add_help=False)
    mode = sc.add_mutually_exclusive_group(required=True)
    mode.add_argument("--every")
    mode.add_argument("--off", action="store_true")
    mode.add_argument("--status", action="store_true")
    sc.add_argument("--yes", action="store_true")
    sc.add_argument("--repo", type=Path)
    o = sub.add_parser("open", add_help=False)
    o.add_argument("--repo", type=Path)
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
    runner = Runner((args.repo or Path.cwd()).resolve(), console)
    top = repo_root(runner)
    console.result(str(top))
    cfg, cfg_path = load_config(repo=top.name)
    state = args.state or cfg.state
    images = cfg.images and not args.no_images
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
    console.line("  Git:     fetches target branches and MR commits over SSH into refs/mr-export/;")
    console.line("           your branches and origin/* stay as they are")
    console.line("────────────────────────────────────────────────")
    if not confirm(console, args.yes):
        console.line("\nStopped. Nothing was read and nothing was written.")
        return 1

    result = fetch(runner, console, root, state, images, datetime.now(), cfg.emergency_branches)
    console.step(f"Write the overview pages into {result.path}")
    index = (render_mod.render(snapshot.load(result.path), cfg.top_labels, cfg.stale_after_hours)
             if not args.no_render else None)
    if index:
        console.result(str(index))

    if index:
        console.step(f"Point {root / 'latest'} at the newest finished snapshot")
        console.result(f"latest -> {retention.update_latest(root).name}")
        console.step(f"Keep the newest {cfg.keep} snapshots (keep in the config), delete older ones")
        gone = retention.prune(root, cfg.keep)
        console.result(", ".join(p.name for p in gone) if gone else "nothing to delete")

    console.line("\n── Result ──────────────────────────────────────")
    console.line(f"  {result.count} merge requests, {result.notes} notes, {result.images} images")
    console.line(f"  Snapshot: {result.path}")
    if index:
        console.line(f"  Open:     xdg-open {index}")
    for f in result.failures:
        console.note(f)   # notes also reach a quiet run's journal
    if result.failures:
        console.note(f"{len(result.failures)} item(s) missing - the overview says so at the top.")
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
        runner = Runner((args.repo or Path.cwd()).resolve(), console)
        top = repo_root(runner)
        cfg, _ = load_config(repo=top.name)
        root = cfg.out_dir / top.name
        current = retention.current(root)
        path = current or newest_snapshot(root)   # hand-made folders count when nothing else exists
        if path is None:
            console.note(f"No snapshot under {root} - run 'mr-export fetch' first, or name a folder.")
            return 1
        console.step(f"Newest snapshot of {top.name}")
        console.result(f"latest -> {path.name}" if current else str(path))
    snap = snapshot.load(path.resolve())
    if args.snapshot is not None:   # <out_dir>/<repo>/<snapshot>: the parent folder names the repo
        cfg, _ = load_config(repo=snap.path.parent.name)
    console.step(f"Write index.html and one page per merge request into {snap.path}")
    index = render_mod.render(snap, cfg.top_labels, cfg.stale_after_hours)
    console.result(f"{len(snap.mrs)} merge requests")
    console.line(f"\n  Open: xdg-open {index}")
    print(index)
    return 0


LAUNCHER = Path(__file__).resolve().parents[2] / "mr-export"   # dev/mr-export/mr-export


def cmd_schedule(args, console: Console) -> int:
    runner = Runner((args.repo or Path.cwd()).resolve(), console)
    top = repo_root(runner)
    runner.repo = top
    if args.status:
        print(schedule.status(runner, console, top))
        return 0
    name = schedule.unit_name(top)
    if args.off:
        console.line(f"\n  Stop and remove the timer {name} for {top}.")
        if not confirm(console, args.yes):
            return 1
        schedule.remove(runner, console, top)
        return 0
    try:
        every = schedule.parse_every(args.every)
    except ValueError as e:
        console.note(str(e))
        return 2
    console.line(f"\n── mr-export schedule ──────────────────────────")
    console.line(f"  Every {every} while you are logged in: mr-export fetch --yes --quiet --repo {top}")
    console.line(f"  Files in {schedule.unit_dir()}:")
    for fname, content in schedule.unit_files(LAUNCHER, top, every).items():
        console.line(f"\n  {fname}")
        for line in content.splitlines():
            console.line(f"    {line}")
    console.line("────────────────────────────────────────────────")
    if not confirm(console, args.yes):
        console.line("\nStopped. Nothing was written.")
        return 1
    schedule.install(runner, console, LAUNCHER, top, every)
    console.line(f"\n  Check later with: mr-export schedule --status")
    return 0


def cmd_open(args, console: Console) -> int:
    runner = Runner((args.repo or Path.cwd()).resolve(), console)
    top = repo_root(runner)
    cfg, _ = load_config(repo=top.name)
    root = cfg.out_dir / top.name
    page = root / "latest" / "index.html"
    if not page.is_file():
        console.note(f"No overview at {page} - run 'mr-export fetch' first.")
        return 1
    app = browser.flatpak_without_access(runner, page)
    if app:
        console.note(f"Your default browser ({app}) is a Flatpak and cannot read {cfg.out_dir}.")
        console.note("It would show the overview, but every link from it would fail. Either open it in a")
        console.note("browser that is not a Flatpak, or allow read access to that one folder once:")
        console.line(f"      {browser.override_command(app, cfg.out_dir)}")
        console.line("  (shown, not run; 'flatpak override --user --reset " + app + "' takes it back)")
    browser.open_page(runner, page)
    print(page)
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
    console = Console(quiet=bool(getattr(args, "quiet", False)))
    try:
        commands = {"fetch": cmd_fetch, "render": cmd_render, "open": cmd_open, "schedule": cmd_schedule}
        return commands[args.cmd](args, console)
    except ConfigError as e:
        print(f"Error in config: {e}", file=sys.stderr)
        return 2
    except (CommandError, FileNotFoundError, FetchLocked) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
