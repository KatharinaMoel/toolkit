# wt on macOS — first test run

`wt` has macOS stand-ins for the Linux-only tools it uses (see
[README › macOS](./README.md#macos)), but nobody has run it on a real Mac yet.
These steps check it without any project database, in a throw-away repo under
`mktemp`. They take about five minutes. Run them in Terminal (zsh) from the
`toolkit` checkout; nothing outside the temporary folders is changed.

If a step does not show what *Verify* says, please copy the full output of that
step into the issue or message.

## 1. Check the tools

```bash
/usr/bin/env bash --version | head -1; git --version; command -v lsof realpath setsid ss
```

Verify: a bash version (3.2 is fine), git 2.31 or newer, a path for `lsof`
(`/usr/sbin/lsof`). No `setsid` and no `ss` is expected — `wt` does without them.

## 2. Run the test suite

```bash
bash dev/wt/test_wt.sh 2>&1 | tail -20
```

Verify: the last line is `alle Tests gruen` (German: all tests green). The lines
before it start with `ok    mac:` — those check the stand-ins. It takes one or two
minutes.

## 3. Run the test suite with the stock bash 3.2

Only needed if step 1 showed a bash newer than 3.2 (for example from Homebrew):

```bash
PATH="/bin:/usr/bin:/usr/sbin:$PATH" /bin/bash dev/wt/test_wt.sh 2>&1 | tail -3
```

Verify: again `alle Tests gruen`.

## 4. Make a throw-away repo with a branch

```bash
WT="$PWD/dev/wt/wt"
T=$(mktemp -d) && cd "$T"
git init -q -b main demo && git -C demo commit -q --allow-empty -m init
git clone -q --bare demo demo.git && git -C demo.git branch feat/x main
git -C demo remote add origin "$T/demo.git" && git -C demo fetch -q origin
cd demo && "$WT" --help | head -1
```

Verify: `wt - Worktrees mit erklaerten Schritten`. (If `git commit` asks for
your name, set `user.name` and `user.email` first.)

## 5. Create a worktree and find it

```bash
"$WT" new --branch feat/x 2>&1 | tail -3
"$WT" path feat/x
"$WT" list 2>/dev/null
```

Verify: `new` ends with `Fertig.` and a `cd …/demo-worktrees/feat-x` line;
`path` prints one path ending in `/demo-worktrees/feat-x` (it may start with
`/private/var/…` — that is the real path behind `/var`); `list` shows `demo
[main]` and `feat-x [feat/x]`.

## 6. Port check (lsof instead of ss)

```bash
python3 -m http.server 8000 --bind 127.0.0.1 >/dev/null 2>&1 & sleep 1
"$WT" run @ 2>&1 | tail -1
kill %1
```

Verify: `Fehler: auf Port 8000 lauscht schon ein Server …` (port 8000 is taken).
`wt` stops before it would start `manage.py`.

## 7. Running server blocks `wt drop` (lsof instead of /proc)

```bash
( cd ../demo-worktrees/feat-x && exec -a "python manage.py runserver" sleep 60 ) & sleep 1
"$WT" drop feat/x 2>&1 | tail -1
kill %1
```

Verify: `Fehler: in feat-x laeuft noch manage.py (PID …) …` and the folder
`../demo-worktrees/feat-x` still exists.

## 8. Remove the worktree and clean up

```bash
"$WT" drop feat/x 2>&1 | tail -1; ls ../demo-worktrees
cd / && rm -rf "$T"
```

Verify: `drop` ends with a note about closing the IDE window, and `ls` prints
nothing (the folder is empty).

Not covered here: `wt ide` with a real IDE, `wt cd` via `wt.zsh`, `--db` with
Docker Desktop or Podman, and `--mr` against a real GitLab or GitHub.
