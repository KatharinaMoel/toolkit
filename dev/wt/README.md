# wt — disposable git worktrees, explained as they run

Review a GitLab merge request or work on a second branch **without touching
your main checkout** — and run several in parallel.

## The problem

`glab mr checkout <nr>` switches the branch in your main working tree. That
disturbs every other session working there, and two reviews at once are
impossible. Worse: if the project uses a local database, an MR that ships
migrations mutates the shared schema for every other branch.

## The idea

- One **disposable worktree per MR**, created detached on GitLab's
  `refs/merge-requests/<nr>/head` ref — no local branch, no branch collisions,
  the main tree stays untouched.
- Optionally one **database copy per MR** via Postgres template cloning
  (`createdb -T` — a fast file-level copy). Migrations hit only the copy;
  the base database stays clean.
- Every step is printed with a one-line explanation before it runs
  (*explain-then-run*), so using the tool teaches you the underlying git.

## Usage

```text
wt new --mr <nr> [--db] [--ide]  # disposable worktree from the MR ref (+ DB copy, + open in IDE)
wt new --branch <name> [--ide]   # working worktree from a (remote) branch
wt drop <nr|slug> [--db]         # remove worktree (and the DB copy)
wt list                          # show worktrees and existing review DB copies
wt path <nr|slug|.>              # print the path, nothing else; `.` = main checkout
wt pick                          # fuzzy picker (fzf): main checkout + all worktrees -> path
wt ide [<nr|slug|.>]             # open in your IDE (IDE_CMD, default `pycharm`); no arg: picker
wt cd [--ide] [<nr|slug|.>]      # cd there; no arg: picker (needs the shell integration)
```

Everything is addressed by **folder**, not by branch: the picker lists folder
names with the branch currently checked out there in brackets. The main
checkout is `.` or its folder name (e.g. `wt cd myproject`) — so a worktree
for the branch `main` (`wt new --branch main`) is simply `wt cd main`.
If the main checkout is not on `TARGET_BRANCH` (and that branch exists
locally), `wt` prints a hint whenever you switch there; it never switches
branches itself. `wt drop` refuses the main checkout.

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
- `wt cd <nr|slug>` jumps into an existing worktree, `wt cd .` back to the
  main checkout, plain `wt cd` opens the picker (Esc leaves you where you are)
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
come from the first file found of:

1. `<repo>/.worktree.conf` — committed, if a team shares the flow
2. `~/.config/wt/<reponame>.conf` — personal, keeps the repo clean

See [example.conf](example.conf) for all variables. Real config files contain
internal names (containers, databases, paths) — keep them local.

## Requirements

- Bash, Git ≥ 2.23
- `wt pick` and argument-less `wt cd` / `wt ide` need [fzf](https://github.com/junegunn/fzf)
- `--db` steps additionally need Docker **or** Podman (docker CLI emulation)
  with a running Postgres container
- Tested on Fedora Linux 44 against a self-hosted GitLab; the
  `refs/merge-requests/<nr>/head` refs are standard GitLab server behaviour

## Install

```bash
ln -s "$(pwd)/wt" ~/.local/bin/wt                  # from this directory; ~/.local/bin on PATH
echo "source $(pwd)/wt.zsh" >> ~/.zshrc            # optional: auto-cd + `wt cd`
sudo dnf install fzf                               # optional: the picker
```
