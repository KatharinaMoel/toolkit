# wt – Spickzettel

Alle Befehle auf einen Blick, dazu was `wt` dabei ausführt. Vollständige Regeln:
`wt --help`, `wt help run`. Welcher Befehl welche Bausteine nutzt:
[bausteine.svg](bausteine.svg). Einrichtung an einem Beispielprojekt: [GUIDE.md](GUIDE.md).

Die Beispielwerte stammen aus [example.conf](example.conf): Repo-Kürzel `abc`,
`manage.py` unter `app/`, Postgres-Container `my_postgres_container` mit der
Stamm-DB `my_project_db`, DB-Kopien mit dem Präfix `review_`.

## Ziele

Gelten für `path`, `cd`, `ide`, `run`. `setup` nimmt alle außer dem Hauptordner;
`drop` nur Nummer, Ordner oder Branch und nie den Worktree, in dem du stehst.

| Ziel | Bedeutung |
|---|---|
| `.` | der Worktree, in dem du stehst (auch aus einem Unterordner) |
| `@` · `abc` · Name des Hauptordners | der Hauptordner |
| `813` · `mr-813` · `abc-mr-813` · `abc-feature-x` | ein Worktree-Ordner in `<repo>-worktrees/` |
| `feature/x` | ein Branch: der Worktree, in dem er ausgecheckt ist, egal wo (auch von der IDE oder `git worktree add` angelegt); ein gleichnamiger Ordner geht vor |
| `/absoluter/pfad` | ein Worktree dieses Repos |

## Befehle

### Anlegen und einrichten

| Befehl | Was er tut |
|---|---|
| `wt new --mr <nr> --db` | Wegwerf-Worktree vom MR-Ref, mit eigener Kopie der Stamm-DB (mit `wt.zsh` endet es im Worktree); `--pr` ist dasselbe für GitHub |
| `wt new --branch <name>` | Arbeits-Worktree von einem bestehenden (Remote-)Branch; zweigt keinen neuen Branch ab. `--db` für eine eigene DB-Kopie, `--ide` öffnet die IDE |
| `wt setup .` | bestehenden Worktree nachträglich einrichten wie `wt new`: `COPY_FILES` kopieren, `LINK_DIRS` verlinken, `requirements.txt` vergleichen. Überschreibt nie, beliebig oft lauffähig |
| `wt setup . --db` | dasselbe plus eigene DB-Kopie (`abc-feature-x` → `review_feature_x`) und Settings-Shim |

### Benutzen

| Befehl | Was er tut |
|---|---|
| `wt run .` | `manage.py runserver` im Worktree, in dem du stehst. Port: Hauptordner `PORT_BASE` (8000), MR-Ordner 8000 + nr mod 1000, sonst fest 9xxx aus dem Ordnernamen; belegt → Abbruch. DB: Shim da → Kopie, sonst Stamm-DB (wt sagt es vorher) |
| `wt run . --mr` | dasselbe, Port vom offenen MR/PR zum Branch (`glab`/`gh`-Abfrage); `--mr <nr>` ohne Netz, `--port <n>` fest, `runserver 0.0.0.0:9000` eigene Adresse |
| `wt run . migrate` | beliebiger `manage.py`-Befehl mit denselben Settings: `migrate`, `makemigrations`, `shell`, `showmigrations`, `test` … Ohne DB-Kopie warnt wt vor `migrate` auf der Stamm-DB |
| `wt run @` | Server im Hauptordner (Port 8000, Stamm-DB) |
| `wt run <nr\|ordner\|branch>` | dasselbe von überall, ohne `cd` |
| `wt help run` | alle Port- und Settings-Regeln von `wt run` mit Beispielen |

### Wechseln und finden

| Befehl | Was er tut |
|---|---|
| `wt cd` | in einen Worktree wechseln (Auswahlliste), braucht `wt.zsh`; `wt cd --ide <ziel>` öffnet zusätzlich die IDE |
| `wt cd @` | zurück in den Hauptordner |
| `wt path <ziel>` | nur den Pfad ausgeben, z. B. `cd "$(wt path feature/x)"` – geht in jeder Shell |
| `wt pick` | Hauptordner oder Worktree aus einer Liste (fzf) wählen, Pfad ausgeben |
| `wt ide <ziel>` | Worktree in der IDE öffnen (`IDE_CMD`, Standard `pycharm`) |
| `wt list` | Worktrees und vorhandene DB-Kopien zeigen |

### Aufräumen

| Befehl | Was er tut |
|---|---|
| `wt drop <nr\|ordner\|branch> --db` | Worktree entfernen, DB-Kopie löschen (Name aus dem Shim; ohne Shim nur bei MR-Ordnern); nie `.` oder `@`; `--force` bei uncommitteten Änderungen |

### Konfiguration

| Eintrag | Bedeutung |
|---|---|
| `<repo>/.worktree.conf` | Werte fürs ganze Team; wird zuerst gelesen |
| `~/.config/wt/<repo>.conf` | persönliche Werte; überschreibt die Team-Datei. Listen mit `+=` ergänzen, z. B. `LINK_DIRS+=(".notizen")` |
| `WT_PREFIX="abc"` | Repo-Kürzel vor jedem Worktree-Ordner (`abc-mr-721`); `721`, `mr-721` und `abc-mr-721` finden denselben Ordner; `abc` allein ist der Hauptordner; `""` = bewusst ohne |

## Von Hand – was wt ausführt

Dieselben Schritte ohne wt. wt zeigt die Befehle, die etwas verändern oder abfragen,
selbst an, bevor sie laufen; Port-Berechnung, Port-Prüfung und das Lesen des Shims laufen still.

- `H` = Hauptordner, z. B. `~/src/myproject`
- `W` = der Worktree, z. B. `~/src/myproject-worktrees/abc-mr-813`
- `P` = `python` des aktiven venv, sonst `RUN_PYTHON`, z. B. `H/.venv/bin/python`

**Faustregel Datenbank:** Liegt der Shim `app/settings_review.py` im Worktree, läuft alles mit
`--settings=app.settings_review` auf der DB-Kopie, sonst mit `--settings=app.settings_local`
auf der Stamm-DB.

### `wt new --mr 813`

```bash
git -C H fetch origin '+refs/merge-requests/813/head:refs/mr/813'    # GitHub: refs/pull/813/head
git -C H worktree add --detach W refs/mr/813
# dann die Schritte von wt setup (Dateien, Links, requirements-Vergleich)
```

### `wt new --mr 813 --db`

```bash
# vorher: gibt es review_813 schon? (dann Abbruch)
docker exec my_postgres_container psql -U postgres -Atc "SELECT datname FROM pg_database"
# dann wie wt new --mr 813, danach:
docker exec my_postgres_container createdb -U postgres -T my_project_db review_813
echo app/settings_review.py >> H/.git/info/exclude                   # nur beim ersten Mal
# W/app/settings_review.py schreiben:
#   from app.settings_local import *
#   DATABASES['default']['NAME'] = 'review_813'
```

### `wt new --branch feature/x`

```bash
# mit --db vorher: gibt es review_feature_x schon? (dann Abbruch, auch wenn ein Shim darauf zeigt)
# Branch lokal vorhanden:
git -C H worktree add ~/src/myproject-worktrees/abc-feature-x feature/x
# sonst vom Remote, mit lokalem Tracking-Branch:
git -C H fetch -q origin feature/x
git -C H worktree add --track -b feature/x ~/src/myproject-worktrees/abc-feature-x origin/feature/x
# dann die Schritte von wt setup; mit --db wie wt setup . --db; mit --ide am Ende: setsid -f pycharm W
```

### `wt setup .`

```bash
# Dateien kopieren (COPY_FILES; nur wenn im Worktree noch nicht da)
cp H/.env W/.env
cp H/app/settings_local.py W/app/settings_local.py
# Ordner verlinken (LINK_DIRS; nur wenn noch nicht da; erst Eintrag in H/.git/info/exclude)
ln -s H/app/media W/app/media
ln -s H/.venv W/.venv
# requirements prüfen (TARGET_BRANCH, z. B. dev)
git -C H fetch -q origin dev
git -C H diff --stat origin/dev...<commit von W> -- requirements.txt    # leer = Haupt-venv passt
```

### `wt setup . --db`

```bash
# wie wt setup ., dann (Name aus dem Ordner: abc-feature-x -> review_feature_x)
docker exec my_postgres_container psql -U postgres -Atc "SELECT datname FROM pg_database"
#   gibt es den Namen schon und zeigt kein Shim in W darauf: Abbruch
docker exec my_postgres_container createdb -U postgres -T my_project_db review_feature_x
echo app/settings_review.py >> H/.git/info/exclude                   # nur beim ersten Mal
# W/app/settings_review.py mit DATABASES['default']['NAME'] = 'review_feature_x'
```

### `wt run .`

```bash
# Port ausrechnen (Ordner ohne MR-Nummer):
echo $((9000 + $(printf '%s' abc-feature-x | cksum | cut -d' ' -f1) % 1000))
ss -tln | grep ':<port> '                                            # belegt: wt bricht ab
# ohne DB-Kopie (Stamm-DB):
cd W && P app/manage.py runserver 127.0.0.1:<port> --settings=app.settings_local
# mit DB-Kopie (Shim in W):
cd W && P app/manage.py runserver 127.0.0.1:<port> --settings=app.settings_review
```

### `wt run @`

```bash
cd H && P app/manage.py runserver 127.0.0.1:8000 --settings=app.settings_local
```

### `wt run . --mr`

```bash
# offenen MR/PR zum Branch suchen, dann wie wt run . mit Port 8000 + nr mod 1000
cd H && glab mr list --source-branch <branch> -F json --jq '.[0].iid'
cd H && gh pr list --head <branch> --json number --jq '.[0].number'   # GitHub
# --mr 813 ohne Abfrage: Port 8813; --port 9123: Port 9123; eigene Adresse: kein Port von wt
```

### `wt run 813`, `wt run . migrate`, `wt run . shell`

```bash
# nach wt new --mr 813 --db (Shim da):
cd ~/src/myproject-worktrees/abc-mr-813 && P app/manage.py runserver 127.0.0.1:8813 --settings=app.settings_review
# jeder andere manage.py-Befehl mit denselben Settings (ohne Shim: app.settings_local, verändert die Stamm-DB):
cd W && P app/manage.py migrate --settings=app.settings_review
cd W && P app/manage.py makemigrations --settings=app.settings_review   # schreibt Migrationsdateien in W
cd W && P app/manage.py shell --settings=app.settings_review
```

### `wt drop 813`

```bash
ss -tln | grep ':8813 '                                              # MR-Ordner: Server läuft noch? dann Abbruch
rm W/app/media W/.venv                                               # nur die Links, nie das Ziel
git -C H worktree remove W                                           # verweigert bei uncommitteten Änderungen: --force
```

Scheitert `worktree remove` an uncommitteten Änderungen, sind die Links schon weg; `wt setup .` holt sie zurück.

### `wt drop 813 --db`

```bash
# vorher: DB-Name aus W/app/settings_review.py lesen (ohne Shim nur bei MR-Ordnern: review_813),
# nie die Stamm-DB, prüfen, dass es ihn gibt
docker exec my_postgres_container psql -U postgres -Atc "SELECT datname FROM pg_database"
# dann wie wt drop 813, danach:
docker exec my_postgres_container dropdb -U postgres review_813
```

### Wechseln, finden, anzeigen

```bash
cd ~/src/myproject-worktrees/abc-mr-813                              # wt cd 813 (Pfad wie wt path 813)
cd ~/src/myproject                                                   # wt cd @
git -C H worktree list --porcelain                                   # wt path feature/x: erst der Ordner
                                                                     #   abc-feature-x, dann feature-x (ohne
                                                                     #   Kürzel), sonst die worktree-Zeile
                                                                     #   über "branch refs/heads/feature/x"
git -C H worktree list --porcelain | fzf                             # wt pick
git -C H worktree list                                               # wt list, dazu:
docker exec my_postgres_container psql -U postgres -Atc "SELECT datname FROM pg_database WHERE datname LIKE 'review_%'"
setsid -f pycharm ~/src/myproject-worktrees/abc-mr-813               # wt ide 813
```
