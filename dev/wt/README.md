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
wt new --mr <nr> [--db]     # disposable worktree from the MR ref (+ DB copy)
wt new --branch <name>      # working worktree from a (remote) branch
wt drop <nr|slug> [--db]    # remove worktree (and the DB copy)
wt list                     # show worktrees and existing review DB copies
```

## What it looks like

Every step prints the exact command plus one line of *why* — using the tool
teaches the underlying git:

```text
$ wt new --mr 42 --db

* Konfig geladen: ~/.config/wt/myproject.conf

> MR-Stand unter benanntem Ref holen (ohne Checkout; + erlaubt Force-Push-Updates)
  $ git -C ~/repos/myproject fetch origin '+refs/merge-requests/42/head:refs/mr/42'

> Wegwerf-Worktree detached anlegen - kein lokaler Branch, keine Branch-Kollision
  $ git -C ~/repos/myproject worktree add --detach ~/repos/myproject-worktrees/mr-42 refs/mr/42

> gitignorte Datei '.env' in den Worktree kopieren (Inhalt wird nie angezeigt)
  $ cp ~/repos/myproject/.env ~/repos/myproject-worktrees/mr-42/.env

* requirements.txt unveraendert gegenueber origin/dev -> Haupt-venv mitnutzen ist ok.

> DB-Kopie 'review_42' per Postgres-Template anlegen (dateiweise Kopie, fast sofort)
  $ docker exec my_postgres_container createdb -U postgres -T my_project_db 'review_42'

* Fertig. Naechste Schritte von Hand:
  cd ~/repos/myproject-worktrees/mr-42
  python app/manage.py runserver 127.0.0.1:8042 --settings=app.settings_review
```

## Configuration

`wt` works with zero config (worktree + file copies only). Project specifics
come from the first file found of:

1. `<repo>/.worktree.conf` — committed, if a team shares the flow
2. `~/.config/wt/<reponame>.conf` — personal, keeps the repo clean

See [example.conf](example.conf) for all variables. Real config files contain
internal names (containers, databases, paths) — keep them local.

## Requirements

- Bash, Git ≥ 2.23
- `--db` steps additionally need Docker **or** Podman (docker CLI emulation)
  with a running Postgres container
- Tested on Fedora Linux 44 against a self-hosted GitLab; the
  `refs/merge-requests/<nr>/head` refs are standard GitLab server behaviour

## Install

```bash
ln -s "$(pwd)/wt" ~/.local/bin/wt   # from this directory; ~/.local/bin on PATH
```
