# mr-export — design decisions

Each entry: the options, the choice, why, and what it costs.

## Python standard library instead of a Bash script

- Options: Bash with `jq` (like `wt`), Python with a Markdown/HTML library, Python stdlib.
- Choice: Python stdlib, started by a small Bash launcher (same pattern as `skill-map`).
- Why: rendering pages from JSON needs escaping, date handling and a little
  Markdown — fragile in Bash, easy in Python. No library means no venv and nothing
  to install on a colleague's machine during an outage.
- Cost: Markdown is only a subset (see README, Limits).

## `glab api` instead of HTTP calls of our own

- Options: `urllib` with a token from the config, `python-gitlab`, `glab api`.
- Choice: `glab api`, run as a subprocess.
- Why: glab already holds the login (keyring), picks host and project from the
  repository, and paginates. The tool never handles a token.
- Cost: glab is a requirement. Tests replace it with a fake that records every call.

## Read-only as a checked property

- Options: trust that we only write GET calls; check them in one place.
- Choice: one method builds every glab call; it accepts only endpoints under `projects/`
  without whitespace, and passes the finished argument list through `assert_read_only`,
  which refuses `-f/-F/--input/--form/-X/--method`. Tests prove both: the guard trips on
  each flag, and every glab call of a full fetch went through it.
- Why: "this only reads" is the promise that lets a team run it against production
  GitLab without a second thought.

## A new folder per run, never an update

- Options: update one snapshot in place, or write a new folder each time.
- Choice: new folder `<YYYY-MM-DD_HHMM>`, `-2`, `-3` when the minute is taken.
- Why: an outage can strike in the middle of a run; a half-written update would
  spoil the last good copy. Old snapshots also show how things stood back then.
- Cost: disk space (images dominate); old folders are deleted by hand.

## Partial results instead of all-or-nothing

- Choice: a failing MR or upload is noted, the run continues, `meta.json` lists the
  gaps, the overview shows them on top, the affected MR page says so, the exit code
  is 1. Only a failing or unreadable list stops the run — then no folder is created.
- `meta.json` is written right after the folder, with `"complete": false`, and again
  at the end. A read stopped by Ctrl-C or a crash therefore never looks finished:
  the overview says it did not finish, and `render` without a folder skips it.
- Why: during flaky availability, 55 of 56 MRs are worth far more than none.

## Repeated calls shown once

- Options: print every call (about 170 for 56 MRs), or show each kind once.
- Choice: the first MR's three calls and the first image download are shown in
  full with their explanation; the rest run as one result line each.
- Why: explain-then-run is about understanding what happens; a wall of identical
  commands hides the one line that failed.

## Images: plain name on disk, encoded name in the page

- GitLab links may carry percent-encoded names (`screen%20one.png`). The file is
  stored under the decoded name and the page links the encoded form, so the
  browser finds it. Names with `/`, `\`, a leading dot, or an invalid secret are
  never downloaded or linked — nothing can be written outside `uploads/<secret>/`.

## Copyable git commands quote branch names

- Git allows `$ ( ) | ;` in branch names. The commands on each MR page are meant to
  be pasted into a shell, so the target branch is `shlex.quote`d; HTML escaping alone
  would not stop a crafted name from running.

## Only this project's uploads

- An upload link counts only when it is relative (`/uploads/<secret>/<file>` at the
  start of a link target). Absolute upload URLs of other projects stay plain links:
  asking this project for them would only fail. Uploads that are not images (a PDF)
  are linked to the local copy as well.

## Offline pages without scripts from elsewhere

- No web fonts, no CDN; system font stack, light and dark via `prefers-color-scheme`.
  The only script is the filter box on the index, inline.
- Everything from GitLab is HTML-escaped first; links become `href` only for
  `http(s)` and for GitLab-relative paths (prefixed with the host) — the project's
  own URLs from the snapshot go through the same check.
