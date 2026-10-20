# wt — disposable git worktrees, explained as they run

Review a GitLab merge request or GitHub pull request, or work on a second branch **without touching
your main checkout** — and run several in parallel.

## The problem

`glab mr checkout <nr>` switches the branch in your main working tree. That
disturbs every other session working there, and two reviews at once are
impossible. Worse: if the project uses a local database, an MR that ships
migrations mutates the shared schema for every other branch.

## The idea

- One **disposable worktree per MR**, created detached on the forge's read-only ref (GitLab `refs/merge-requests/<nr>/head`,
  GitHub `refs/pull/<nr>/head`) — no local branch, no branch collisions,
  the main tree stays untouched.
- Optionally one **database copy per MR** via Postgres template cloning
  (`createdb -T` — a fast file-level copy). Migrations hit only the copy;
  the base database stays clean.
- Every step is printed with a one-line explanation before it runs
  (*explain-then-run*), so using the tool teaches you the underlying git.

## Usage

```text
wt new --mr <nr> [--db] [--ide]      # disposable worktree from the MR/PR ref (+ DB copy, + open in IDE); --pr is an alias
wt new --branch <name> [--db] [--ide] # working worktree from a (remote) branch
wt setup <target> [--db]             # set up an existing worktree the way `wt new` would (never overwrites)
wt run <target> [args]               # manage.py in that worktree (default: runserver); `wt help run`
wt drop <target> [--db]              # remove worktree (and its DB copy)
wt list                              # show worktrees and existing review DB copies
wt path <target>                     # print the path, nothing else
wt pick                              # fuzzy picker (fzf): main checkout + all worktrees -> path
wt ide [<target>]                    # open in your IDE (IDE_CMD, default `pycharm`); no arg: picker
wt cd [--ide] [<target>]             # cd there; no arg: picker (needs the shell integration)
```

Which command uses which building block — and that only `wt new` contains the
steps of `wt setup` — is shown in [bausteine.svg](bausteine.svg) (labels in German).

### Targets

| Target | Means |
|---|---|
| `.` | the worktree the shell stands in (also from a subfolder) |
| `@`, the main folder's name, the `WT_PREFIX` tag | the main checkout |
| `721`, `mr-721`, `abc-mr-721`, `feat-x` | a worktree folder in the sibling folder `<repo>-worktrees/` |
| `feat/x` | a branch: the worktree where it is checked out, wherever it lives and however its folder is named (worktrees made by an IDE or plain `git worktree add`) |
| `/abs/path` | a worktree of this repo |

A folder name wins over a branch of the same name. Every target must be a
worktree of this repo; anything else is refused. The picker lists folder
names with the branch currently checked out there in brackets, so a worktree
for the branch `main` (`wt new --branch main`) is simply `wt cd main`.
Branch and folder names typed for `wt new` may contain letters, digits and `. _ - /` only;
paths found by `git worktree list` may contain anything and are quoted with
`printf %q` in every command `wt` shows and runs.
`TARGET_BRANCH` defaults to the remote's default branch (`refs/remotes/<REMOTE>/HEAD`); `REMOTE` and `FORGE` (gitlab/github, auto-detected from the remote URL) are config variables too. The requirements check only runs when the project has a `requirements.txt`, and never aborts the run.

If the main checkout is not on `TARGET_BRANCH` (and that branch exists
locally), `wt` prints a hint whenever you switch there; it never switches
branches itself. `wt drop` refuses the main checkout and the worktree the
shell stands in, however they are named (`.`, folder or branch).

### Setting up an existing worktree

`wt setup <target> [--db]` runs the same steps as `wt new` on a worktree that
already exists — one made by PyCharm, Claude Code or a colleague's `git
worktree add`: copy `COPY_FILES`, symlink `LINK_DIRS`, compare
`requirements.txt`, and with `--db` create a DB copy plus the settings shim.
Every step that finds its result already there says so and does nothing, so
it is safe to run again; a file in the worktree is never overwritten. The
main checkout is the source of all of it and is refused.

DB copies are named `DB_COPY_PREFIX` + MR number for `mr-<nr>` folders, and
`DB_COPY_PREFIX` + the folder name without the `WT_PREFIX` tag otherwise
(`abc-feat-x` -> `review_feat_x`; lower case, `_` for anything but letters and
digits; more than 63 bytes is refused). The shim in a worktree is what ties a
copy to it: `wt setup --db` and `wt new --db` refuse a copy of that name that
no shim here points to (it belongs to another worktree), and `wt drop --db`
drops the DB the shim names — checked before the worktree goes, and never the
template or a name without `DB_COPY_PREFIX`. Without a shim, `wt drop --db`
drops `<prefix><nr>` for MR folders only; for other folders it prints the
`dropdb` command instead of guessing.

### Ports and settings for `wt run`

For `runserver`, the first match wins: `--port N`; the main checkout gets
`PORT_BASE` (8000); an `mr-<nr>` folder gets `PORT_BASE + nr mod 1000`;
`--mr <nr>` gives the same without network; plain `--mr` asks `glab`
(GitLab) or `gh` (GitHub) for the open MR/PR of the checked-out branch;
otherwise a fixed port 9000-9999 from the folder name — the same on every
start. A lookup that finds nothing, or a missing tool, is a note, never an
abort. An address you pass yourself (`runserver 8001`) is used as is.

With `SETTINGS_SHIM_PATH` configured, the shim decides the database: present
in the worktree -> `RUN_SETTINGS` (the copy); missing -> `SETTINGS_SHIM_IMPORT`
(the main DB), with a note — a server on the main DB keeps `createdb -T` from
copying it, and `migrate` there changes it for every branch. Without
`SETTINGS_SHIM_PATH`, `RUN_SETTINGS` is always appended. An explicit
`--settings` is left alone.

`wt run` uses the active venv (`python`); without one it falls back to `RUN_PYTHON`
from the config (relative to the main checkout, e.g. its venv), then to `python` from PATH.

Explanations go to **stderr**, results to **stdout** — so `cd "$(wt path 42)"`
and other substitutions stay clean.

## What it looks like

Every step prints the exact command plus one line of *why* — using the tool
teaches the underlying git:

```text
$ wt new --mr 42 --db

* Konfig geladen: ~/.config/wt/myproject.conf

* MR-Stand unter benanntem Ref holen (ohne Checkout; + erlaubt Force-Push-Updates)
  > git -C ~/repos/myproject fetch origin '+refs/merge-requests/42/head:refs/mr/42'

* Wegwerf-Worktree detached anlegen - kein lokaler Branch, keine Branch-Kollision
  > git -C ~/repos/myproject worktree add --detach ~/repos/myproject-worktrees/mr-42 refs/mr/42

* gitignorte Datei '.env' in den Worktree kopieren (Inhalt wird nie angezeigt)
  > cp ~/repos/myproject/.env ~/repos/myproject-worktrees/mr-42/.env

* requirements.txt unveraendert gegenueber origin/dev -> Haupt-venv mitnutzen ist ok.

* DB-Kopie 'review_42' per Postgres-Template anlegen (dateiweise Kopie, fast sofort)
  > docker exec my_postgres_container createdb -U postgres -T my_project_db 'review_42'

* Fertig. Naechste Schritte von Hand:
  python app/manage.py runserver 127.0.0.1:8042 --settings=app.settings_review

* Wechseln nach mr-42 [detached] (zurueck: cd -)
  > cd ~/repos/myproject-worktrees/mr-42
```

(The last step comes from the shell integration below; without it, `wt`
prints the `cd` line for you to run yourself.)

## Shell integration (zsh)

A script runs as a child process and can never change its parent shell's
directory — that is why tools like `nvm` or `z` are shell functions. `wt.zsh`
wraps the script in a small function: it asks the script for the path
(`wt path` or `wt pick`) and does the `cd` itself, shown like every other step.

```bash
echo 'source /path/to/toolkit/dev/wt/wt.zsh' >> ~/.zshrc
```

With it loaded:

- `wt new …` ends inside the new worktree (`cd -` takes you back)
- `wt cd <target>` jumps into an existing worktree, `wt cd @` back to the
  main checkout, `wt cd .` to the root of the worktree you are in, plain
  `wt cd` opens the picker (Esc leaves you where you are)
- `wt cd --ide …` additionally opens the target in your IDE
- everything else passes through unchanged
- non-interactive shells (agents, scripts, hooks) never get their cwd moved

## PyCharm (and other IDEs)

`wt ide <x>` runs `IDE_CMD <path>` detached from the terminal. Whether that
opens a new window or replaces the current one is PyCharm's setting
*Settings | Appearance & Behavior | System Settings | Open project in*.
Notes from setting this up with PyCharm 2026.2 (verify against your version):

- **One window per worktree** works best: each window has exactly one Git root,
  so the commit tool commits to that worktree's branch. All windows share one
  IDE process and memory; close a worktree's window when you're done
  (`wt drop` reminds you).
- There is **no documented command-line flag to *attach*** a directory to an
  open project — attaching is only a button in the "open project" dialog.
- PyCharm's own **Git | Worktrees** tab (switch by double-click) only works for
  projects with a single Git root. Attached worktrees or leftover entries under
  *Settings | Version Control | Directory Mappings* turn the project into a
  multi-root project and hide the tab. *Remove from Project View* removes the
  folder but **not** its VCS mapping — remove that one separately.

## Configuration

`wt` works with zero config (worktree + file copies only). Project specifics
come from these files, both read if present, the later one winning:

1. `<repo>/.worktree.conf` — committed, if a team shares the flow
2. `~/.config/wt/<reponame>.conf` — personal, keeps the repo clean

See [example.conf](example.conf) for all variables, and [GUIDE.md](GUIDE.md) for
a worked example that derives a config step by step from a real project. Forge, remote and target branch are auto-detected; override them with `FORGE`, `REMOTE`, `TARGET_BRANCH`. Real config files contain
internal names (containers, databases, paths) — keep them local.

### Folder prefix

`WT_PREFIX` (repo config only; an exported environment variable is ignored) puts a short tag in front of every worktree folder: `WT_PREFIX="abc"` gives `abc-mr-721` and `abc-feat-x`. That keeps folders recognisable outside the repo (IDE recent projects, window titles, `wt pick`) when several repos have worktrees like `mr-3`. Letters and digits only, taken literally (no case change); anything else aborts. Only the folder name changes: DB copies (`<DB_COPY_PREFIX><nr>`), ports and branch names stay as they are.

Lookup (`wt path/cd/ide/setup/run/drop`) finds the same folder for `721`, `mr-721` and `abc-mr-721`: first `<prefix>-<slug>`, then the slug without the tag (`5` finds a folder `mr-5`). A tag is never stripped, so `wt new --branch` refuses a branch whose slug starts with the tag (`wt path abc-fix` could not tell branch `abc-fix` from the folder `abc-fix` of branch `fix`) and a branch whose slug is `mr-<digits>` (branch `123` or `mr/123` would share its folder with MR 123). `wt drop` and `wt run` derive the MR number (port, DB copy) from the folder name that was found (`mr-721` or `abc-mr-721`), never from what was typed.

Folders created before the tag was set are still found; `wt` shows the `git worktree move <old> <new>` command to rename them but never runs it (close the IDE window on the folder first). `wt new` refuses to create a second folder next to such an old one for the same MR/branch.

If `WT_PREFIX` is unset in every config, `wt` uses plain folder names and `wt new` ends with a reminder to pick a tag. `WT_PREFIX=""` means plain names on purpose and silences the reminder.

## Requirements

- Bash, Git ≥ 2.23
- `wt pick` and argument-less `wt cd` / `wt ide` need [fzf](https://github.com/junegunn/fzf)
- `--db` steps additionally need Docker **or** Podman (docker CLI emulation)
  with a running Postgres container
- Tested on Fedora Linux 44 against a self-hosted GitLab; the GitHub path (`--pr`) is covered by offline tests;
  `refs/merge-requests/<nr>/head` (GitLab) and `refs/pull/<nr>/head` (GitHub) are standard server-side refs

## Install

```bash
ln -s "$(pwd)/wt" ~/.local/bin/wt                  # from this directory; ~/.local/bin on PATH
echo "source $(pwd)/wt.zsh" >> ~/.zshrc            # optional: auto-cd + `wt cd`
sudo dnf install fzf                               # optional: the picker
```
