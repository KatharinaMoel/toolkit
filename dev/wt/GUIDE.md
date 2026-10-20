# Setting up wt for a project — a worked example

This guide sets up `wt` for one concrete kind of project: a **Django app with
Postgres in Docker**, reviewed through GitLab merge requests. The project is
anonymized as `myproject`, but the layout, the steps and the terminal output
come from a real run against a real project.

The approach transfers to other projects: first write down what the main checkout has
that a fresh worktree lacks, then pick the `wt` variable that supplies each
piece. The [checklist at the end](#adapting-it-to-your-project) is the short
version.

`wt` prints its explanations in German. The output below is the real output
with names and paths replaced; each block is followed by a short English summary.

## 1. Starting point: what the main checkout has

The main checkout is `~/src/myproject`. A developer there can already start
the app with `python app/manage.py runserver --settings=app.settings_local_docker`.
That works because of things git does **not** carry:

| In the main checkout | Why a fresh worktree lacks it |
|---|---|
| `.env` | gitignored, holds local secrets and switches |
| `app/settings_local_docker.py` | gitignored, created from `app/settings_local_docker_example.py`, points Django at the Docker database |
| `.venv-3.12/` (the Python environment, ~700 MB) | gitignored, built once by an install script |
| `app/media/` (uploaded images, ~2 GB) | gitignored, synced from cloud storage |
| A Postgres container `myproject-postgres` with the database `myproject` | lives outside the repo |

Two more facts about the project matter:

- Merge requests target `dev`, not the default branch.
- Many merge requests ship database migrations. Running them against the shared
  database changes it for every other branch.

## 2. From need to config

| Need | wt mechanism | Variable |
|---|---|---|
| The gitignored files `.env` and the local settings file | copied into the worktree, never overwritten | `COPY_FILES` |
| The venv and the media folder | symlinked from the main checkout, no copy | `LINK_DIRS` |
| A database a review may migrate | one copy per worktree via `createdb -T`, plus a two-line settings file (the *shim*) pointing at it | `--db`, `DB_*`, `SETTINGS_SHIM_*` |
| Starting the server in the worktree | `wt run`, with port and settings chosen per worktree | `RUN_*`, `PORT_BASE` |
| Checking whether the MR changes dependencies | `requirements.txt` compared against the target branch | `TARGET_BRANCH` |

**Copy or link?** Files are small and may differ per worktree, so they are copied.
Folders are large and identical, so they are linked. A link is shared,
though: an image uploaded in a review lands in the main checkout's media folder,
and `pip install` in a worktree changes the main venv.

**Why a shim?** The shim is a generated settings file that imports the local
settings and changes only the database name:

```python
from app.settings_local_docker import *  # noqa: F401,F403
DATABASES['default']['NAME'] = 'review_42'
```

It ties the copy to the worktree: `wt run` uses the copy when the shim is there
and the main database when it is not, and `wt drop --db` drops the database the
shim names (without a shim: `review_<nr>` for MR folders only; for other folders it
prints the `dropdb` command instead). It never drops the template or a name without
`DB_COPY_PREFIX`.

## 3. Prerequisite: the main checkout runs

`wt` only copies and links what already exists. Before configuring it, check
in the main checkout:

- [ ] `.env` exists (in this project it is created from `.example.env`)
- [ ] the venv exists, and you know its **exact folder name** (`ls -d .venv*`), see [pitfalls](#7-pitfalls)
- [ ] the Postgres container runs: `docker ps` lists `myproject-postgres`
- [ ] the database you want as the template exists in it, migrated or restored from a dump
- [ ] the local settings file exists and points at that database
- [ ] `runserver` starts and the site loads in the browser

If one of these fails, fix it first. `wt` cannot repair a main checkout that does not work.

## 4. Install

```bash
git clone https://github.com/KatharinaMoel/toolkit.git ~/src/toolkit
ln -s ~/src/toolkit/dev/wt/wt ~/.local/bin/wt          # ~/.local/bin must be on PATH
git -C ~/src/myproject rev-parse --show-toplevel        # wt only runs inside a git repo
(cd ~/src/myproject && wt list)                          # check: shows the main checkout
```

Only the `wt` script is required. Everything else is optional:

| Optional | Gives you | Without it |
|---|---|---|
| `source ~/src/toolkit/dev/wt/wt.zsh` in `~/.zshrc` | `wt new` ends inside the new worktree; `wt cd <target>` | `cd "$(wt path 42)"` (works in any shell) |
| `fzf` | `wt pick`, `wt cd` / `wt ide` without arguments | always name the target |
| Docker or Podman | `--db` | no database copies |
| `glab` (GitLab) or `gh` (GitHub) | `wt run <x> --mr` without a number finds the branch's open MR | pass the number: `--mr 42` |

You don't need a token or any extra login. `wt new --mr 42` fetches the merge request with a plain
`git fetch` over your existing `origin` remote, so if `git pull` works, this does too.

## 5. Write the config

`wt` reads **both** of these files if they exist, in this order, and a later value
wins:

1. `<repo>/.worktree.conf` — can be committed, for values the whole team shares
2. `~/.config/wt/<reponame>.conf` — personal, overrides the shared file

`<reponame>` is the folder name of the main checkout, here `myproject`.
The split for this project: the first half can go into `.worktree.conf` (or,
until the team agrees on it, into your personal file too), the second half belongs
in `~/.config/wt/myproject.conf`.

```bash
# --- project-wide: follows from the repo layout --------------------------
TARGET_BRANCH="dev"                         # MRs target dev
COPY_FILES=(".env" "app/settings_local_docker.py")
SETTINGS_SHIM_PATH="app/settings_review.py" # generated, never committed
SETTINGS_SHIM_IMPORT="app.settings_local_docker"
RUN_MANAGE="app/manage.py"
RUN_SETTINGS="app.settings_review"
DB_COPY_PREFIX="review_"
PORT_BASE=8000

# --- personal: differs per machine ----------------------------------------
WT_PREFIX="mp"                              # folders become mp-mr-42, mp-feat-x
DB_CONTAINER="myproject-postgres"           # docker ps --format '{{.Names}}'
DB_TEMPLATE="myproject"                     # the database the copies start from
DB_USER="postgres"
LINK_DIRS=("app/media" ".venv-3.12")        # use your venv's real folder name
RUN_PYTHON=".venv-3.12/bin/python"          # used when no venv is active
IDE_CMD="pycharm"
```

Why each personal value is personal:

- **`DB_CONTAINER` / `DB_TEMPLATE`:** the container is named by whoever started it,
  and some developers keep several databases (a fresh one, an imported dump).
- **The venv name:** it depends on which install route was used (next section).
- **`COPY_FILES` / `SETTINGS_SHIM_IMPORT`** are shared here only because everyone uses
  the same file name for the local settings. If people use different names,
  these two move to the personal file.
- Personal helper folders (notes, scratch files) can be added to `LINK_DIRS` in the
  personal file only.

Never put passwords in either file. The database password belongs in `.env` or
the local settings file, which `wt` copies without showing its content.

## 6. First run

### Create: `wt new --mr 42 --db`

This run uses the personal file only; with both files, wt prints one
`Konfig geladen` line per file.

```text
* Konfig geladen: ~/.config/wt/myproject.conf

* Forge: gitlab (aus der URL von 'origin'; FORGE in der Konfig setzen, falls falsch)

* MR-Stand unter benanntem Ref holen (ohne Checkout; + erlaubt Force-Push-Updates)
  > git -C ~/src/myproject fetch origin
      +refs/merge-requests/42/head:refs/mr/42

* Wegwerf-Worktree detached anlegen - kein lokaler Branch, keine Branch-Kollision
  > git -C ~/src/myproject worktree add --detach
      ~/src/myproject-worktrees/mp-mr-42 refs/mr/42

* gitignorte Datei '.env' in den Worktree kopieren (Inhalt wird nie angezeigt)
  > cp ~/src/myproject/.env ~/src/myproject-worktrees/mp-mr-42/.env

* gitignorte Datei 'app/settings_local_docker.py' in den Worktree kopieren (Inhalt wird nie angezeigt)
  > cp ~/src/myproject/app/settings_local_docker.py
      ~/src/myproject-worktrees/mp-mr-42/app/settings_local_docker.py

* 'app/media' per Symlink aus dem Hauptbaum einbinden (keine Kopie; Aenderungen darin treffen den Hauptbaum)
  > ln -s ~/src/myproject/app/media ~/src/myproject-worktrees/mp-mr-42/app/media

* '.venv-3.12' per Symlink aus dem Hauptbaum einbinden (keine Kopie; Aenderungen darin treffen den Hauptbaum)
  > ln -s ~/src/myproject/.venv-3.12 ~/src/myproject-worktrees/mp-mr-42/.venv-3.12

* Zielbranch aktualisieren, damit der requirements-Vergleich stimmt
  > git -C ~/src/myproject fetch -q origin dev

* requirements.txt unveraendert gegenueber origin/dev -> Haupt-venv mitnutzen ist ok.

* DB-Kopie 'review_42' per Postgres-Template anlegen (dateiweise Kopie, fast sofort)
  > docker exec myproject-postgres createdb -U postgres -T myproject review_42

* Settings-Shim erzeugen: app/settings_review.py (gitignored; fixe 3-Zeilen-Vorlage, zeigt nur auf die DB-Kopie)
    | from app.settings_local_docker import *  # noqa: F401,F403
    | DATABASES['default']['NAME'] = 'review_42'

* Fertig. Naechste Schritte von Hand:
  wt run 42   (Server starten; wt run 42 migrate fuer manage.py-Befehle)
```

What happened: wt fetched the MR into a named ref and created a worktree in
*detached* mode, so there is no local branch to collide with. It copied the two
gitignored files and linked media and the venv. Because `requirements.txt` is unchanged
against `dev`, the shared venv fits. Finally it cloned the database and wrote the shim.
(Left out here and in the blocks below: each `docker exec … psql` lookup, git's
own progress lines, the one-time `echo … >> .git/info/exclude` steps that keep the
links and the shim out of `git status`, the `> cat > …` line before the shim, and,
without `wt.zsh`, a final `cd <path>` hint.)

### Start: `wt run 42`

This run had the main venv activated (`source ~/src/myproject/.venv-3.12/bin/activate`).
Without an active venv, wt falls back to `RUN_PYTHON`, says
`kein venv aktiv, RUN_PYTHON aus der Konfig`, and calls that interpreter by its full path.

```text
* Port 8042 (MR 42 aus dem Ordnernamen)
* Datenbank: DB-Kopie 'review_42' (app/settings_review.py im Worktree)
* Python-Umgebung: aktives venv ~/src/myproject/.venv-3.12
    Interpreter: ~/src/myproject/.venv-3.12/bin/python
    Version:     Python 3.12.x
* manage.py im Worktree mp-mr-42 ausfuehren (Ctrl+C beendet den Server)
  > cd ~/src/myproject-worktrees/mp-mr-42 && python
      app/manage.py runserver 127.0.0.1:8042 --settings=app.settings_review
```

What happened: the port is `PORT_BASE + (MR number mod 1000)`, so several reviews
run side by side (MR 43 gets 8043; MR 1042 would also get 8042, and wt refuses to
start a second server on a busy port). The shim exists, so the server uses the copy. Run migrations
the same way: `wt run 42 migrate` changes only `review_42`.

### Remove: `wt drop 42 --db`

```text
* Symlink 'app/media' entfernen (nur der Link, das Ziel im Hauptbaum bleibt)
* Symlink '.venv-3.12' entfernen (nur der Link, das Ziel im Hauptbaum bleibt)
* Worktree entfernen (verweigert bei uncommitteten Aenderungen; dann bewusst 'wt drop mp-mr-42 --force')
  > git -C ~/src/myproject worktree remove ~/src/myproject-worktrees/mp-mr-42
* Falls mp-mr-42 in PyCharm offen war: das Fenster schliessen - es zeigt jetzt auf einen geloeschten Ordner.
* DB-Kopie wegwerfen - die Stamm-DB war nie betroffen
  > docker exec myproject-postgres dropdb -U postgres review_42
```

What happened (the `> rm …` commands under the symlink steps and the psql lookup
are left out): wt removes the links (only the links, never their targets), then the
worktree, then the copy the shim named. The fetched ref `refs/mr/42` stays
in the main repo; it is small, and the next `wt new --mr 42` updates it.

## 7. Pitfalls

- **Two venv names.** In the example project the Makefile creates `.venv`, while
  the install script and the `manage.py` wrapper use `.venv-3.12`. `LINK_DIRS` and
  `RUN_PYTHON` must name the folder that actually exists. Check with `ls -d .venv*`.
- **`make` deletes the wrong venv.** If the Makefile says
  `VIRTUAL_ENV ?= ${PWD}/.venv` and recreates it with `rm -rf $(VIRTUAL_ENV)`, an
  *activated* main venv sets `VIRTUAL_ENV` in the environment, and `make venv`
  in a worktree deletes the **main** venv. Run `deactivate` first, or pass the path
  explicitly: `make venv VIRTUAL_ENV="$PWD/.venv"`.
- **A copy needs a quiet template.** `createdb -T` refuses while anyone is
  connected to the template database, including a `runserver` on the main checkout.
  Stop that server first. `wt run` without a shim reminds you of this.
- **Migrations on the main database.** `wt run <x> migrate` in a worktree
  *without* a shim migrates the main database, which is also the template for every
  future copy. wt prints a warning but does not stop; run `wt setup <x> --db`
  first to give that worktree its own copy.
- **Shared links.** Uploads in a review land in the main media folder;
  `pip install` in a worktree changes the main venv. If `wt new` reports a
  changed `requirements.txt`, delete the venv link in that worktree and build a
  separate venv there (after `deactivate`). Activate that venv before `wt run`;
  otherwise `RUN_PYTHON` still points at the main venv.
- **Existing worktrees.** Worktrees made by an IDE or `git worktree add` lack
  the copied files and links. `wt setup <folder-or-branch> [--db]` adds them and
  never overwrites anything.

## Adapting it to your project

Answer these in your main checkout; each answer is one config line.

1. Which gitignored files does the app need to start? → `COPY_FILES`
2. Which large gitignored folders can be shared? → `LINK_DIRS`
3. Which branch do merge requests target? → `TARGET_BRANCH`
4. Where is `manage.py`? → `RUN_MANAGE`
5. Which Postgres container and which database should copies start from?
   → `DB_CONTAINER`, `DB_TEMPLATE`, `DB_USER`
6. Which settings module holds the local database connection? → `SETTINGS_SHIM_IMPORT`;
   choose a gitignored path for the shim → `SETTINGS_SHIM_PATH`, `RUN_SETTINGS`
7. Which values differ between developers? → personal file `~/.config/wt/<reponame>.conf`;
   the rest can go into a committed `.worktree.conf`
8. Does the main checkout start cleanly? If not, fix that before anything else.

All variables and their defaults: [example.conf](example.conf).
