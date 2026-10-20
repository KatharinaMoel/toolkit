# wt — design: `.` = here, `@` = main checkout, branch lookup, `wt setup`, ports without an MR

## Why

`wt` worked well for MR review worktrees (`wt new --mr 721 --db`, then
`wt run 721`: symlinked media, a DB copy, port 8721). It fell short in three
places:

1. **A worktree without an MR number** (a feature branch, maybe no MR yet):
   `wt run` gave up ("kein Port ableitbar") and always appended
   `RUN_SETTINGS`, whose module only exists after `--db`.
2. **A worktree not made by `wt`** (by an IDE, an agent or a plain
   `git worktree add`): no gitignored files, no symlinks, no DB copy.
   `wt link` only did the symlinks, and `wt` only found folders in
   `<repo>-worktrees/`.
3. **Remembering** the variants and the shell commands behind them, including
   `manage.py migrate` / `makemigrations` (which `wt run <x> migrate` already
   ran, but nobody knew).

Success: from any worktree, `wt setup .` once, then `wt run .` and
`wt run . migrate` — without knowing an MR number or a settings module name.

## Decisions

### Targets (every command that takes one: path, cd, ide, run, setup, drop)

| Target | Means |
|---|---|
| `.` | the worktree the shell stands in, also from a subfolder (changed: it used to mean the main checkout) |
| `@` | the main checkout, in every repo |
| main folder name, `WT_PREFIX` tag | the main checkout as before; the tag is new |
| `721`, `mr-721`, `abc-mr-721`, `feat-x` | a worktree folder as before |
| a branch name | the worktree where that branch is checked out — fallback after the folder lookup |

- **Lookup order:** folder first (as `find_wt` did), then the worktree that has
  the branch checked out (`git worktree list --porcelain`, wherever the folder
  is; unique, git never checks a branch out twice). Detached MR worktrees are
  reached by number only.
- `@` rather than another symbol: zsh leaves it alone, and `resolve_slug`
  never allows it in a folder name, so it cannot collide. `..` would suggest
  the parent folder, `^` and `~` are expanded by zsh.
- `.` follows the logical `$PWD` (longest worktree path it starts with), so a
  linked folder such as `<worktree>/.reviews`, physically inside the main
  checkout, still means the worktree. `git rev-parse --show-toplevel` is the
  fallback.
- Every resolved target must be a worktree of this repo; anything else is
  refused. Resolved paths are symlink-free.
- `wt drop` refuses the main checkout and the worktree the shell stands in,
  judged by the resolved folder, not the typed name. A branch slug equal to
  `WT_PREFIX` is refused by `wt new --branch`, like one starting with it.

### Port for `wt run` (first match wins)

1. `--port N`
2. main checkout → `PORT_BASE`; folder `mr-<nr>` / `<tag>-mr-<nr>` →
   `PORT_BASE + nr mod 1000` (unchanged)
3. `--mr <nr>` → the same, without network
4. `--mr` alone → ask the forge for the open MR/PR of the checked-out branch
   (GitLab `glab mr list --source-branch <b> -F json --jq '.[0].iid'`, GitHub
   `gh pr list --head <b> --json number --jq '.[0].number'`); no hit, no tool,
   no network → a note, then 5
5. otherwise a fixed port `9000 + cksum(folder name) mod 1000` — offline,
   the same on every start, apart from the MR ports

`wt` always says where the port came from. An address passed by the user
(`runserver 8001`) is used as is and skips all of this.

### `wt setup <target> [--db]`

Runs the steps `wt new` runs on an existing worktree: copy `COPY_FILES`,
symlink `LINK_DIRS`, compare `requirements.txt`, with `--db` the DB copy and
the settings shim. It is the only command for this; **`wt link` is gone**
(calling it only points to `wt setup`). Nothing is ever overwritten — a step
whose result is already there says so — so it can run again. The main
checkout is the source and is refused. `wt new` uses the same steps, so
`--db` now works for `wt new --branch` too.

### Database copies

- **Name:** `DB_COPY_PREFIX` + MR number for MR folders; otherwise + the
  folder name without the `WT_PREFIX` tag, lower case, `_` for anything but
  letters and digits (`abc-feat-x` → `review_feat_x`). From the folder, not
  the branch, so it survives a `git switch` and works for detached worktrees.
  More than 63 bytes is refused (Postgres would cut it silently).
- **Ownership:** the shim in the worktree decides. `wt setup --db` / `wt new
  --db`: copy exists and this worktree's shim points to it → "already there";
  copy exists but no shim here points to it (`feat-x` and `feat_x` give the
  same name) → abort, never share. `wt new --db` checks before it creates the
  worktree.
- **`wt drop --db`** drops the DB named in the shim, checked before the
  worktree (and the shim with it) is removed, and only if it exists. A shim
  naming `DB_TEMPLATE` or a name without `DB_COPY_PREFIX` is never treated as a
  copy. Without a shim only MR folders drop `<prefix><nr>`; for other folders
  `wt` prints the `dropdb` command instead of guessing whose copy it is.

### Unsaved work in `wt drop`

`git worktree remove` refuses a worktree with uncommitted changes or untracked
files, but only at the end — after `wt drop` has removed the links. A refused
drop used to leave a worktree without `media`, venv and `.reviews`. Now
`wt drop` reads `git status --porcelain -z` first (unquoted paths, so link
names with spaces still match), after the port check and
before anything changes: any line aborts with the files listed and the
command to repeat (`--db` kept) or to force. The links from `LINK_DIRS` are
not counted (an untracked symlink `<dir>` appears when the ignore rule is
`<dir>/`). `--force` skips the check and is passed to `git worktree remove`.

Alternatives: keep relying on `git worktree remove` (old behaviour) — the
refusal comes last, the links are already gone and the `--force` hint drops
`--db`; put the links back after a failed remove — repairs instead of
preventing. Price: one extra `git status` per drop, and a file that appears
between the check and the remove is still caught only by Git.

### Settings for `wt run`

Only when `SETTINGS_SHIM_PATH` is configured: shim present in the worktree →
`RUN_SETTINGS` (the copy); missing → `SETTINGS_SHIM_IMPORT` (the main DB),
with a note before the start and a clear warning before `migrate`. Without
`SETTINGS_SHIM_PATH` the old behaviour stays: `RUN_SETTINGS` is always
appended. An explicit `--settings` is never touched. No new config key.

### Locked template

Without a copy the server runs on the main DB, which is also `DB_TEMPLATE`;
while it runs, `createdb -T` fails. The main-DB note in `wt run` says so, and
the `createdb` error names a server or psql on the main DB as the usual cause.
No abort in advance.

### Smaller calls

- No `wt migrate` alias: `wt run . migrate` / `makemigrations` is enough.
- `wt new --mr` without `--db` ends with `wt run <nr>` instead of `RUN_HINT`,
  which names the shim settings that do not exist then.
- Paths from `git worktree list` may contain anything; every path in a shown
  and executed command is quoted with `printf %q`.

## Non-goals and anti-goals

- Not: zsh completion, other ports for MR worktrees, network lookups without
  `--mr`.
- Never: overwrite a file in a worktree; migrate the main DB silently; run a
  step without showing it first (explain-then-run stays the principle).

## Known limits

- MR 1000, 2000, … share `PORT_BASE` with the main checkout, and two non-MR
  folders can get the same 9xxx port; only the busy-port check catches that.
- A non-MR folder named only by digits gets the DB name of an MR copy.
- `shim_db` reads only the exact line `settings_shim` writes.
- `has_addr` does not recognise `localhost:8001` or `[::]:8000`.
- The `migrate` warning only fires when `migrate` is the first argument.
- `wt drop` on a worktree with submodules or a locked one (`git worktree
  lock`): `git status` is clean, so the links go before `git worktree remove`
  refuses (a locked one even with `--force`). `wt setup .` brings the links back.

## Verification

`bash dev/wt/test_wt.sh` covers targets (`.` from subfolders and linked
folders, `@`, tag, branch lookup outside the worktree folder, non-worktree
paths), ports (fixed, `--mr` with and without number, glab/gh stubs and a
PATH without them), settings choice, `wt setup` (paths with spaces, no
overwrite, idempotence, DB ownership, template and prefix guards, dangling
symlink shim), `wt drop --db` and the `wt link` pointer. A manual test in a
real repo: `wt run <nr>` in an MR worktree, `wt setup .` + `wt run .` in an
IDE-made worktree, `wt setup . --db` + `wt run . migrate`, `wt drop <x> --db`.
