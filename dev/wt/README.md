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

```
wt new --mr <nr> [--db]     # disposable worktree from the MR ref (+ DB copy)
wt new --branch <name>      # working worktree from a (remote) branch
wt drop <nr|slug> [--db]    # remove worktree (and the DB copy)
wt list                     # show worktrees and existing review DB copies
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
