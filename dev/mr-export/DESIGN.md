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

---

# v2 — sync and overview

## Git state in an own ref namespace

- Options: read `origin/*` as the user has it; fetch into `refs/remotes/origin/*`;
  fetch into `refs/mr-export/*`.
- Choice: `refs/mr-export/heads/<branch>` and `refs/mr-export/mr/<iid>`.
- Why: the user's view of the remote must not move under them because a timer ran,
  and their remote-tracking refs may be stale on purpose.
- Cost: refs that `git gc` keeps alive; `git for-each-ref refs/mr-export` lists them,
  `git update-ref -d` removes them.

## "In target" by content, not only by ancestry

- Options: ancestry (`merge-base --is-ancestor`); patch ids (`git cherry`); a test
  merge (`git merge-tree --write-tree`).
- Choice: ancestry first, then a test merge: if merging the MR into the target
  yields the target's own tree, the changes are already there. This replaces the
  spec's `git cherry` / `Local-MR:` trailer idea for this stage: patch ids miss
  multi-commit squashes, and the trailer only exists once Part C merges.
- A conflicting test merge (exit 1) is shown as *unclear*, not *no*: a change that
  was squashed and later edited again on the target conflicts as well.
  `--quiet` is not used — on real MRs it reported success despite conflicts.
  The test merge writes loose objects into `.git`, never refs.
- Why: teams that squash would otherwise see "no" for exactly the MRs that were
  merged by hand. Patch ids miss a squash of several commits.
- Cost: one merge-tree run per unmerged MR; needs Git ≥ 2.38.

## Complete, partial, unfinished

- A run is complete when every read worked, partial when it finished with gaps,
  unfinished when it stopped half-way (meta.json is written with complete=false
  first). `latest` points at the newest complete snapshot, or at a partial one that
  is newer. Pruning keeps the newest `keep` complete ones, and up to `keep` partial
  ones newer than the newest complete one; partial and unfinished ones older than it
  are removed. A `meta.json` without `complete` comes from the first version, which
  wrote it only after a successful run, and counts as complete.
- Why: a string of half-good runs during an outage must not push out the last good
  copy.

## One fetch at a time

- A `flock` on `<out_dir>/<repo>/.fetch.lock`; a second fetch stops at once.
- Why: the timer and a manual run would otherwise race on pruning and `latest`.

## Age computed in the browser

- The page carries the read time and the threshold; a tiny script turns them into
  "read 40 min ago" and colors it after `stale_after_hours`.
- Why: a page written at read time would still say "5 min ago" next week. The timer's
  interval is not known to the page, so the threshold is its own setting. The spec's
  "red when the newest run was unfinished" is not possible on a static page that
  cannot see later runs; an unfinished run is flagged on its own page instead.

## Diff panel

- `git diff <target>...<head>` is stored per MR at read time, so pages need no Git.
  Files with up to 10 changed lines start open; a file is cut after 1500 lines, a page
  after 6000, a line after 2000 characters; files beyond the page budget keep their
  counts and stay listed; binary files are only listed. Diff text in other encodings
  is decoded with replacement characters rather than failing the run.
- MRs whose head cannot be fetched get no diff and no failure: their state says `?`.

## Flatpak browsers

- `open` asks `xdg-mime` for the default HTML handler; when it is a Flatpak whose
  `filesystems` permission covers neither home nor the snapshot folder, it prints the
  `flatpak override` command and still opens the page. It never runs the override.
- Why: through the document portal such a browser sees only the one file; every link
  from the overview fails, which looks like a broken tool.

## Timer as a systemd user unit

- Options: cron; systemd user timer with lingering; without lingering.
- Choice: user timer without lingering, unit name `mr-export-<folder>-<hash>`.
- Why: glab's token sits in the desktop keyring and SSH keys in the session's agent;
  both exist only while the user is logged in. The hash keeps two clones with the same
  folder name apart; `%` in paths is doubled because systemd reads it as a placeholder.

## Images load at once

- Images on MR pages load without `loading="lazy"`: the files are local, and lazy
  images came out empty in headless screenshots and printouts.

## Member list file

- Members are stored as `members.ndjson` (glab's paginated output unchanged), not
  `members.json` as the spec wrote; Part C reads that file.
