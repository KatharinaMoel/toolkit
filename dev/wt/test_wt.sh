#!/usr/bin/env bash
# test_wt.sh - prueft die Pfad-, Auswahl- und IDE-Befehle von wt in einem
# Wegwerf-Repo unter mktemp. Beruehrt weder echte Repos noch ~/.config.
#
#   bash dev/wt/test_wt.sh
#
# fzf und die IDE werden durch Stubs ersetzt: der fzf-Stub waehlt die Zeile,
# die $FZF_PICK enthaelt; der IDE-Stub schreibt seine Argumente in eine Datei.
set -uo pipefail

WT="$(cd "$(dirname "$0")" && pwd)/wt"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home" NO_COLOR=1 COLUMNS=10000 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
unset WT_PREFIX
mkdir -p "$HOME"

# ---------- Stubs ----------
STUBS="$TMP/stubs"
mkdir -p "$STUBS"
cat > "$STUBS/fzf" <<'EOF'
#!/usr/bin/env bash
# Stub: Eingabe merken, Zeile mit $FZF_PICK ausgeben; ohne Treffer wie Esc (130).
tee "$FZF_LOG" | grep -m1 -F -- "${FZF_PICK:-}" || exit 130
EOF
cat > "$STUBS/fake-ide" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$IDE_LOG"
EOF
chmod +x "$STUBS/fzf" "$STUBS/fake-ide"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUBS/ss"; chmod +x "$STUBS/ss"
export PATH="$STUBS:$PATH" FZF_LOG="$TMP/fzf.log" IDE_LOG="$TMP/ide.log"

# ---------- Wegwerf-Repo mit zwei Worktrees ----------
REPO="$TMP/repos/demo"
BASE="$TMP/repos/demo-worktrees"
git init -q -b dev "$REPO"
printf '.idea/\n' > "$REPO/.gitignore"
git -C "$REPO" add .gitignore
git -C "$REPO" -c user.name=t -c user.email=t@t commit -qm init
git -C "$REPO" worktree add -q -b feature/x "$BASE/feature-x"
git -C "$REPO" worktree add -q --detach "$BASE/mr-42"
git -C "$REPO" worktree add -q -b main "$BASE/main"   # Worktree fuer den Branch main
mkdir -p "$HOME/.config/wt"
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# Lokales Bare-Repo als "Remote" (kein Netz): Default-Branch dev, drei Feature-Branches,
# MR 7 nur im GitLab-Namensraum, PR 8 nur im GitHub-Namensraum - so faellt eine
# falsche Forge-Wahl beim Fetch auf.
REMOTE_BARE="$TMP/repos/demo.git"
git clone -q --bare "$REPO" "$REMOTE_BARE"
for b in feat/a feat/b feat/c; do git -C "$REMOTE_BARE" update-ref "refs/heads/$b" refs/heads/dev; done
git -C "$REMOTE_BARE" update-ref refs/merge-requests/7/head refs/heads/feat/a
git -C "$REMOTE_BARE" update-ref refs/pull/8/head refs/heads/feat/b
git -C "$REPO" remote add origin "$REMOTE_BARE"
git -C "$REPO" fetch -q origin
git -C "$REPO" remote set-head origin dev          # origin/HEAD -> dev, wie nach einem clone

# ---------- Mini-Testrahmen ----------
fails=0
ok()   { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; fails=$((fails + 1)); }
expect_eq() { # name erwartet tatsaechlich
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1" "erwartet '$2', bekommen '$3'"; fi
}

# ---------- wt path ----------
cd "$REPO" || exit 1
expect_eq "path @ -> Hauptrepo"         "$REPO"            "$("$WT" path @ 2>/dev/null)"
expect_eq "path . im Hauptrepo -> Hauptrepo" "$REPO"       "$("$WT" path . 2>/dev/null)"
expect_eq "path <reponame> -> Hauptrepo" "$REPO"           "$("$WT" path demo 2>/dev/null)"
expect_eq "path main -> Worktree main"  "$BASE/main"       "$("$WT" path main 2>/dev/null)"
expect_eq "path <slug>"                 "$BASE/feature-x"  "$("$WT" path feature-x 2>/dev/null)"
expect_eq "path <branch mit />"         "$BASE/feature-x"  "$("$WT" path feature/x 2>/dev/null)"
expect_eq "path <nr>"                   "$BASE/mr-42"      "$("$WT" path 42 2>/dev/null)"
expect_eq "path <absoluter Pfad>"       "$BASE/mr-42"      "$("$WT" path "$BASE/mr-42" 2>/dev/null)"
cd "$BASE/mr-42" || exit 1
expect_eq "path . aus einem Worktree"   "$BASE/mr-42"      "$("$WT" path . 2>/dev/null)"
expect_eq "path @ aus einem Worktree"   "$REPO"            "$("$WT" path @ 2>/dev/null)"
mkdir -p "$BASE/mr-42/sub" && cd "$BASE/mr-42/sub" || exit 1
expect_eq "path . aus Worktree-Unterordner" "$BASE/mr-42"  "$("$WT" path . 2>/dev/null)"
# '.' in einem verlinkten Ordner (LINK_DIRS wie .reviews zeigen in den Hauptordner): der Worktree, nicht das Ziel des Links
mkdir -p "$REPO/geteilt" && ln -s "$REPO/geteilt" "$BASE/mr-42/geteilt" && cd "$BASE/mr-42/geteilt" || exit 1
expect_eq "path . in einem Symlink in den Hauptordner -> Worktree" "$BASE/mr-42" "$("$WT" path . 2>/dev/null)"
cd "$REPO" || exit 1; rm "$BASE/mr-42/geteilt"; rmdir "$REPO/geteilt"
cd "$REPO" || exit 1
if "$WT" path gibtsnicht >/dev/null 2>&1; then fail "path unbekannt" "Exit 0"; else ok "path unbekannt -> Fehler"; fi

# Branch-Suche: Worktree an fremdem Ort mit fremdem Ordnernamen (wie von PyCharm angelegt)
git -C "$REPO" worktree add -q -b feat/fremd "$TMP/elsewhere/pycharm-wt"
expect_eq "path <branch> findet fremden Ordner" "$TMP/elsewhere/pycharm-wt" "$("$WT" path feat/fremd 2>/dev/null)"
expect_eq "path <branch> des Hauptordners"      "$REPO"            "$("$WT" path dev 2>/dev/null)"
git -C "$REPO" worktree add -q -b feature-x "$TMP/elsewhere/branch-feature-x"   # Branch heisst wie der Ordner eines anderen Worktrees
expect_eq "path <ordner> geht vor gleichnamigem Branch" "$BASE/feature-x" "$("$WT" path feature-x 2>/dev/null)"
git -C "$REPO" worktree remove "$TMP/elsewhere/branch-feature-x"
ln -s "$REPO" "$TMP/link-auf-demo"
expect_eq "path <Symlink auf Hauptordner> -> echter Pfad" "$REPO" "$("$WT" path "$TMP/link-auf-demo" 2>/dev/null)"
err=$("$WT" path "$TMP/link-auf-demo" 2>&1 >/dev/null)
git -C "$REPO" switch -q -c symlink-probe
err=$("$WT" path "$TMP/link-auf-demo" 2>&1 >/dev/null)
git -C "$REPO" switch -q dev; git -C "$REPO" branch -q -D symlink-probe
if [[ "$err" == *"symlink-probe"* ]]; then ok "path <Symlink auf Hauptordner> prueft den Branch des Hauptordners"
else fail "path <Symlink auf Hauptordner> prueft den Branch des Hauptordners" "$err"; fi
expect_eq "path <absolut, fremder Ort>"          "$TMP/elsewhere/pycharm-wt" "$("$WT" path "$TMP/elsewhere/pycharm-wt" 2>/dev/null)"
cd "$TMP/elsewhere/pycharm-wt" || exit 1
expect_eq "path . im fremden Worktree"           "$TMP/elsewhere/pycharm-wt" "$("$WT" path . 2>/dev/null)"
cd "$REPO" || exit 1
mkdir -p "$TMP/kein-worktree"
err=$("$WT" path "$TMP/kein-worktree" 2>&1 >/dev/null); rc=$?
expect_eq "path <Ordner, kein Worktree> -> Exit 1" "1" "$rc"
if [[ "$err" == *"kein Worktree"* ]]; then ok "path <Ordner, kein Worktree> nennt den Grund"; else fail "path <Ordner, kein Worktree> nennt den Grund" "$err"; fi
git -C "$REPO" worktree remove "$TMP/elsewhere/pycharm-wt"
cd "$BASE/mr-42" || exit 1   # die pick-Tests laufen aus einem Worktree

# ---------- wt pick ----------
out=$(FZF_PICK=feature-x "$WT" pick 2>"$TMP/pick.err")
expect_eq "pick gibt nur den Pfad aus"  "$BASE/feature-x"  "$out"
first=$(head -1 "$FZF_LOG" | cut -f1 | sed "s/ *$//")
expect_eq "pick: Hauptrepo steht zuerst" "demo"            "$first"
if grep -q $'^mr-42 *\t.*← hier' "$FZF_LOG"; then ok "pick markiert aktuellen Worktree"
else fail "pick markiert aktuellen Worktree" "$(cat "$FZF_LOG")"; fi
if grep -q $'^feature-x *\t\[feature/x\]' "$FZF_LOG"; then ok "pick zeigt Branch"
else fail "pick zeigt Branch" "$(cat "$FZF_LOG")"; fi
if grep -q 'fzf' "$TMP/pick.err"; then ok "pick erklaert den Schritt auf stderr"
else fail "pick erklaert den Schritt auf stderr" "$(cat "$TMP/pick.err")"; fi
if FZF_PICK=nichtvorhanden "$WT" pick >/dev/null 2>&1; then fail "pick Abbruch" "Exit 0"
else ok "pick Abbruch (Esc) -> Exit != 0"; fi

# fzf fehlt: PATH nur mit den noetigsten Werkzeugen, ohne fzf
NOFZF="$TMP/nofzf"
mkdir -p "$NOFZF"
for c in bash git dirname basename cut sed grep tput fold; do
  p=$(command -v "$c") && ln -s "$p" "$NOFZF/$c"
done
err=$(PATH="$NOFZF" "$WT" pick 2>&1 >/dev/null)
if [[ "$err" == *"fzf"*"nicht gefunden"* ]]; then ok "pick ohne fzf -> klarer Hinweis"
else fail "pick ohne fzf -> klarer Hinweis" "$err"; fi

# ---------- wt ide ----------
wait_for_ide() { local n=0; while [ "$n" -lt 50 ]; do [ -s "$IDE_LOG" ] && return 0; sleep 0.1; n=$((n + 1)); done; return 1; }
rm -f "$IDE_LOG"
"$WT" ide 42 >/dev/null 2>&1
wait_for_ide
expect_eq "ide <nr> oeffnet Worktree"   "$BASE/mr-42"      "$(cat "$IDE_LOG" 2>/dev/null)"
rm -f "$IDE_LOG"
FZF_PICK=Hauptrepo "$WT" ide >/dev/null 2>&1
wait_for_ide
expect_eq "ide ohne Argument -> Auswahl" "$REPO"           "$(cat "$IDE_LOG" 2>/dev/null)"
printf 'IDE_CMD="gibt-es-nicht"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" ide 42 2>&1 >/dev/null)
if [[ "$err" == *"gibt-es-nicht"* ]]; then ok "ide mit fehlendem IDE_CMD -> Hinweis"
else fail "ide mit fehlendem IDE_CMD -> Hinweis" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# ---------- wt run: Interpreter ----------
cat > "$STUBS/python" <<'EOF'
#!/usr/bin/env bash
echo "PATH-PYTHON $*"
EOF
mkdir -p "$REPO/.venv/bin"
cat > "$REPO/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
echo "REPO-VENV $*"
EOF
chmod +x "$STUBS/python" "$REPO/.venv/bin/python"
cd "$BASE/mr-42" || exit 1
printf 'IDE_CMD="fake-ide"\nRUN_PYTHON=".venv/bin/python"\n' > "$HOME/.config/wt/demo.conf"
out=$(env -u VIRTUAL_ENV "$WT" run 42 shell 2>/dev/null)
expect_eq "run ohne venv nutzt RUN_PYTHON"   "REPO-VENV manage.py shell" "$out"
out=$(VIRTUAL_ENV=/irgendwo "$WT" run 42 shell 2>/dev/null)
expect_eq "run: aktives venv hat Vorrang"    "PATH-PYTHON manage.py shell" "$out"
err=$(VIRTUAL_ENV=/irgendwo "$WT" run 42 shell 2>&1 >/dev/null)
if [[ "$err" == *"Python-Umgebung"*"/irgendwo"*"Interpreter:"* ]]; then ok "run nennt aktives venv und Interpreter vorab"
else fail "run nennt aktives venv und Interpreter vorab" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"
out=$(env -u VIRTUAL_ENV "$WT" run 42 shell 2>/dev/null)
expect_eq "run ohne RUN_PYTHON -> python"    "PATH-PYTHON manage.py shell" "$out"
printf 'IDE_CMD="fake-ide"\nRUN_PYTHON=".venv/bin/gibtsnicht"\n' > "$HOME/.config/wt/demo.conf"
printf 'IDE_CMD="fake-ide"\nRUN_PYTHON=".venv/bin/python"\n' > "$HOME/.config/wt/demo.conf"
err=$(env -u VIRTUAL_ENV "$WT" run 42 shell 2>&1 >/dev/null)
if [[ "$err" == *"RUN_PYTHON"*"$REPO/.venv/bin/python"*"Version:"* ]]; then ok "run nennt RUN_PYTHON-Pfad und Version vorab"
else fail "run nennt RUN_PYTHON-Pfad und Version vorab" "$err"; fi
printf 'IDE_CMD="fake-ide"\nRUN_PYTHON=".venv/bin/gibtsnicht"\n' > "$HOME/.config/wt/demo.conf"
err=$(env -u VIRTUAL_ENV "$WT" run 42 shell 2>&1 >/dev/null)
if [[ "$err" == *"gibtsnicht"*"nicht ausfuehrbar"* ]]; then ok "run mit falschem RUN_PYTHON -> Fehler"
else fail "run mit falschem RUN_PYTHON -> Fehler" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# ---------- Hauptordner nicht auf TARGET_BRANCH ----------
cd "$REPO" || exit 1
err=$("$WT" path @ 2>&1 >/dev/null)
if [[ "$err" != *"TARGET_BRANCH"* ]]; then ok "Hauptordner auf dev -> keine Warnung"
else fail "Hauptordner auf dev -> keine Warnung" "$err"; fi
git -C "$REPO" switch -q -c anderes
err=$("$WT" path @ 2>&1 >/dev/null)
if [[ "$err" == *"anderes"*"dev"* ]]; then ok "Hauptordner auf anderem Branch -> Warnung"
else fail "Hauptordner auf anderem Branch -> Warnung" "$err"; fi
git -C "$REPO" switch -q dev
printf 'IDE_CMD="fake-ide"\nTARGET_BRANCH="gibtsnicht"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" path @ 2>&1 >/dev/null)
if [[ "$err" != *"TARGET_BRANCH"* ]]; then ok "TARGET_BRANCH lokal unbekannt -> keine Warnung"
else fail "TARGET_BRANCH lokal unbekannt -> keine Warnung" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# ---------- wt drop ----------
cd "$REPO" || exit 1
if "$WT" drop . >/dev/null 2>&1; then fail "drop ." "Exit 0"; else ok "drop . -> verweigert"; fi
if "$WT" drop @ >/dev/null 2>&1; then fail "drop @" "Exit 0"; else ok "drop @ -> verweigert"; fi
cd "$BASE/mr-42" || exit 1
err=$("$WT" drop . 2>&1 >/dev/null); rc=$?
if [ "$rc" -ne 0 ] && [ -d "$BASE/mr-42" ] && [[ "$err" == *"herauswechseln"* ]]; then ok "drop . aus einem Worktree -> verweigert"
else fail "drop . aus einem Worktree -> verweigert" "rc=$rc $err"; fi
cd "$REPO" || exit 1
# Branch des Hauptordners: die Branch-Suche trifft den Hauptordner - nie entfernen, keine Links loeschen
mkdir -p "$TMP/media-ziel"; ln -s "$TMP/media-ziel" "$REPO/media"
printf 'IDE_CMD="fake-ide"\nLINK_DIRS=(media)\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" drop dev 2>&1 >/dev/null); rc=$?
if [ "$rc" -ne 0 ] && [ -L "$REPO/media" ] && [[ "$err" == *"Hauptordner"* ]]; then ok "drop <branch des Hauptordners> -> verweigert, Links unversehrt"
else fail "drop <branch des Hauptordners> -> verweigert, Links unversehrt" "rc=$rc $err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"; rm "$REPO/media"
# Ordner unter der eigenen Shell, per Branch angesprochen
git -C "$REPO" worktree add -q -b feat/hier "$TMP/elsewhere/hier"
mkdir -p "$TMP/elsewhere/hier/sub" && cd "$TMP/elsewhere/hier/sub" || exit 1
err=$("$WT" drop feat/hier 2>&1 >/dev/null); rc=$?
if [ "$rc" -ne 0 ] && [ -d "$TMP/elsewhere/hier" ] && [[ "$err" == *"herauswechseln"* ]]; then ok "drop <branch des eigenen Worktrees> -> verweigert"
else fail "drop <branch des eigenen Worktrees> -> verweigert" "rc=$rc $err"; fi
cd "$REPO" || exit 1
"$WT" drop feat/hier >/dev/null 2>&1; rc=$?
expect_eq "drop <branch, fremder Ort> von aussen -> Exit 0" "0" "$rc"
# Ordnername mit Apostroph (z.B. von PyCharm angelegt): landet nie ungeschuetzt in einem Befehl
git -C "$REPO" worktree add -q -b feat/q "$TMP/kat's/y"
expect_eq "path <branch, Pfad mit '>" "$TMP/kat's/y" "$("$WT" path feat/q 2>/dev/null)"
err=$("$WT" drop feat/q 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [ ! -e "$TMP/kat's/y" ]; then ok "drop <branch, Pfad mit '> entfernt den Worktree"
else fail "drop <branch, Pfad mit '> entfernt den Worktree" "rc=$rc $err"; fi
# Ordner geloescht, Worktree noch eingetragen (prunable)
git -C "$REPO" worktree add -q -b feat/weg "$TMP/elsewhere/weg"; rm -rf "$TMP/elsewhere/weg"
err=$("$WT" drop feat/weg 2>&1 >/dev/null); rc=$?
if [ "$rc" -ne 0 ] && [[ "$err" == *"worktree prune"* ]]; then ok "drop <branch, Ordner geloescht> -> Hinweis auf git worktree prune"
else fail "drop <branch, Ordner geloescht> -> Hinweis auf git worktree prune" "rc=$rc $err"; fi
git -C "$REPO" worktree prune
if "$WT" drop demo >/dev/null 2>&1; then fail "drop <reponame>" "Exit 0"; else ok "drop <reponame> -> verweigert"; fi
if [ -d "$REPO/.git" ]; then ok "Hauptrepo unversehrt"; else fail "Hauptrepo unversehrt" "fehlt"; fi
mkdir -p "$BASE/feature-x/.idea" && : > "$BASE/feature-x/.idea/workspace.xml"
err=$("$WT" drop feature-x 2>&1)
if [ ! -d "$BASE/feature-x" ]; then ok "drop trotz gitignorierter .idea/"
else fail "drop trotz gitignorierter .idea/" "$err"; fi
if [[ "$err" == *"PyCharm"* ]]; then ok "drop erinnert ans Fensterschliessen"
else fail "drop erinnert ans Fensterschliessen" "$err"; fi

# ---------- wt new: Zielbranch, Forge, Remote ----------
cd "$REPO" || exit 1
# Regression: TARGET_BRANCH zeigt auf einen Branch, den der Remote nicht hat -> frueher
# brach 'git fetch' den Lauf ab, Abschlusshinweise und --ide kamen nie.
printf 'IDE_CMD="fake-ide"\nTARGET_BRANCH="gibtsnicht"\n' > "$HOME/.config/wt/demo.conf"
: > "$REPO/requirements.txt"
rm -f "$IDE_LOG"
err=$("$WT" new --branch feat/a --ide 2>&1 >/dev/null); rc=$?
expect_eq "new: Zielbranch fehlt auf Remote -> Exit 0" "0" "$rc"
if [[ "$err" == *"requirements-Vergleich entfaellt"*"Fertig"* ]]; then ok "new: fehlender Zielbranch -> Hinweis statt Abbruch"
else fail "new: fehlender Zielbranch -> Hinweis statt Abbruch" "$err"; fi
wait_for_ide
expect_eq "new --ide laeuft trotz fehlendem Zielbranch" "$BASE/feat-a" "$(cat "$IDE_LOG" 2>/dev/null)"
"$WT" drop feat-a >/dev/null 2>&1
rm -f "$REPO/requirements.txt"

# TARGET_BRANCH leer -> Default-Branch des Remotes (origin/HEAD = dev)
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"
: > "$REPO/requirements.txt"
err=$("$WT" new --branch feat/b 2>&1 >/dev/null)
if [[ "$err" == *"unveraendert gegenueber origin/dev"* ]]; then ok "new: TARGET_BRANCH leer -> origin/HEAD (dev)"
else fail "new: TARGET_BRANCH leer -> origin/HEAD (dev)" "$err"; fi
"$WT" drop feat-b >/dev/null 2>&1
rm -f "$REPO/requirements.txt"

# ohne requirements.txt: gar kein venv-Vergleich (kein Python-Projekt)
err=$("$WT" new --branch feat/b 2>&1 >/dev/null)
if [[ "$err" != *"requirements"* && "$err" == *"Fertig"* ]]; then ok "new: ohne requirements.txt kein venv-Vergleich"
else fail "new: ohne requirements.txt kein venv-Vergleich" "$err"; fi
"$WT" drop feat-b >/dev/null 2>&1

# origin/HEAD fehlt (Repo per 'git remote add' statt clone): wt erfragt ihn einmalig
git -C "$REPO" symbolic-ref -d refs/remotes/origin/HEAD
err=$("$WT" new --branch feat/c 2>&1 >/dev/null); rc=$?
expect_eq "new: ohne origin/HEAD -> Exit 0" "0" "$rc"
if [[ "$err" == *"remote set-head origin --auto"* ]]; then ok "new: ohne origin/HEAD -> set-head wird erklaert"
else fail "new: ohne origin/HEAD -> set-head wird erklaert" "$err"; fi
expect_eq "new: origin/HEAD danach gesetzt" "origin/dev" "$(git -C "$REPO" symbolic-ref -q --short refs/remotes/origin/HEAD)"
"$WT" drop feat-c >/dev/null 2>&1

# Forge: Bare-Remote ohne github.com in der URL -> gitlab -> refs/merge-requests
err=$("$WT" new --mr 7 2>&1 >/dev/null); rc=$?
expect_eq "new --mr (gitlab) -> Exit 0" "0" "$rc"
if [[ "$err" == *"Forge: gitlab"*"refs/merge-requests/7/head:refs/mr/7"* ]]; then ok "new --mr: GitLab-Ref"
else fail "new --mr: GitLab-Ref" "$err"; fi
expect_eq "new --mr: Worktree mr-7" "$BASE/mr-7" "$("$WT" path 7 2>/dev/null)"
"$WT" drop 7 >/dev/null 2>&1

# Forge aus der URL: github.com -> refs/pull; insteadOf lenkt den Fetch auf das Bare-Repo um
git -C "$REPO" config url."$REMOTE_BARE".insteadOf "git@github.com:x/y.git"
git -C "$REPO" remote set-url origin "git@github.com:x/y.git"
err=$("$WT" new --pr 8 2>&1 >/dev/null); rc=$?
expect_eq "new --pr (github-URL) -> Exit 0" "0" "$rc"
if [[ "$err" == *"Forge: github"*"PR-Stand"*"refs/pull/8/head:refs/mr/8"* ]]; then ok "new --pr: GitHub-Ref aus URL erkannt"
else fail "new --pr: GitHub-Ref aus URL erkannt" "$err"; fi
expect_eq "new --pr: Worktree mr-8" "$BASE/mr-8" "$("$WT" path 8 2>/dev/null)"
"$WT" drop 8 >/dev/null 2>&1
git -C "$REPO" remote set-url origin "$REMOTE_BARE"

# FORGE aus der Konfig schlaegt die URL; ungueltiger Wert -> Fehler
printf 'IDE_CMD="fake-ide"\nFORGE="github"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" new --mr 8 2>&1 >/dev/null)
if [[ "$err" == *"refs/pull/8/head"* && "$err" != *"Forge: "* ]]; then ok "new --mr: FORGE aus Konfig"
else fail "new --mr: FORGE aus Konfig" "$err"; fi
"$WT" drop 8 >/dev/null 2>&1
printf 'IDE_CMD="fake-ide"\nFORGE="bitbucket"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" list 2>&1 >/dev/null)
if [[ "$err" == *"FORGE muss"* ]]; then ok "FORGE ungueltig -> Fehler"
else fail "FORGE ungueltig -> Fehler" "$err"; fi

# REMOTE aus der Konfig; unbekannter Remote -> klarer Fehler
git -C "$REPO" remote add upstream "$REMOTE_BARE"
git -C "$REPO" fetch -q upstream
printf 'IDE_CMD="fake-ide"\nREMOTE="upstream"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" new --mr 7 2>&1 >/dev/null); rc=$?
expect_eq "new --mr mit REMOTE=upstream -> Exit 0" "0" "$rc"
if [[ "$err" == *"fetch upstream"*"refs/merge-requests/7/head:refs/mr/7"* ]]; then ok "new --mr: REMOTE aus Konfig"
else fail "new --mr: REMOTE aus Konfig" "$err"; fi
"$WT" drop 7 >/dev/null 2>&1
printf 'IDE_CMD="fake-ide"\nREMOTE="nirgends"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" new --mr 7 2>&1 >/dev/null)
if [[ "$err" == *"Remote 'nirgends' gibt es"* ]]; then ok "new: unbekannter REMOTE -> Fehler"
else fail "new: unbekannter REMOTE -> Fehler" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# ---------- wt new: Haertung (Injection, Forge-Erkennung, fehlender Zielbranch) ----------
# Netz ist tabu: GIT_ALLOW_PROTOCOL=file laesst git ssh/https sofort verweigern; geprueft wird nur wts stderr.
# shellcheck disable=SC2016  # absichtlich unexpandiert: der Name soll als Text im Branch stehen
EVIL='x;touch${IFS}PWNED;#'
INJ_SRC="$TMP/inj/src"
git init -q -b main "$INJ_SRC"
git -C "$INJ_SRC" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
git -C "$INJ_SRC" branch "$EVIL"
git -C "$INJ_SRC" branch feat/ok
git clone -q --bare "$INJ_SRC" "$TMP/inj/evil.git"
git -C "$TMP/inj/evil.git" symbolic-ref HEAD "refs/heads/$EVIL"
git clone -q "$TMP/inj/evil.git" "$TMP/inj/repo"
printf 'x\n' > "$TMP/inj/repo/requirements.txt"
git -C "$TMP/inj/repo" add requirements.txt
git -C "$TMP/inj/repo" -c user.name=t -c user.email=t@t commit -qm req
cd "$TMP/inj/repo" || exit 1
err=$("$WT" new --branch feat/ok 2>&1 >/dev/null); rc=$?
expect_eq "Injection: Branch-Name mit Shell-Zeichen -> Exit 0" "0" "$rc"
if [ -z "$(find "$TMP" -name PWNED)" ]; then ok "Injection: nichts ausgefuehrt (keine Datei PWNED)"
else fail "Injection: nichts ausgefuehrt (keine Datei PWNED)" "$(find "$TMP" -name PWNED)"; fi
if [[ "$err" == *"ungewoehnliche Zeichen"* ]]; then ok "Injection: unsicherer Default-Branch wird gemeldet"
else fail "Injection: unsicherer Default-Branch wird gemeldet" "$err"; fi
# Ein Branch-Name aus --branch laeuft an der Zeichenpruefung vorbei: hier schuetzt nur das Quoting.
# shellcheck disable=SC2016  # absichtlich unexpandiert
EVIL2='main;touch${IFS}PWNED2;#'   # 'main' existiert: ohne Quoting liefe der fetch durch und dann touch
git -C "$INJ_SRC" branch "$EVIL2"
git -C "$TMP/inj/evil.git" fetch -q "$INJ_SRC" "refs/heads/$EVIL2:refs/heads/$EVIL2"
"$WT" new --branch "$EVIL2" >/dev/null 2>&1
if [ -z "$(find "$TMP" -name PWNED2)" ]; then ok "Injection: --branch mit Shell-Zeichen wird nicht ausgefuehrt"
else fail "Injection: --branch mit Shell-Zeichen wird nicht ausgefuehrt" "$(find "$TMP" -name PWNED2)"; fi
# Ein einfaches Anfuehrungszeichen wuerde aus dem '$wtpath' der run-Strings ausbrechen.
# shellcheck disable=SC2016  # absichtlich unexpandiert
EVIL3="a'\$(touch\${IFS}QX)'"
err=$("$WT" new --branch "$EVIL3" 2>&1 >/dev/null); rc=$?
expect_eq "Injection: Name mit ' -> abgelehnt" "1" "$rc"
if [[ "$err" == *"ungewoehnlichen Zeichen"* ]]; then ok "Injection: Name mit ' -> Hinweis auf die erlaubten Zeichen"
else fail "Injection: Name mit ' -> Hinweis auf die erlaubten Zeichen" "$err"; fi
if [ -z "$(find "$TMP" -name QX)" ]; then ok "Injection: Name mit ' wird nicht ausgefuehrt"
else fail "Injection: Name mit ' wird nicht ausgefuehrt" "$(find "$TMP" -name QX)"; fi
err=$("$WT" drop "$EVIL3" 2>&1 >/dev/null); rc=$?
expect_eq "Injection: drop mit ' -> abgelehnt" "1" "$rc"

# Single-Branch-Clone: TARGET_BRANCH="dev" wird geholt, landet aber nicht unter origin/dev
SB_SRC="$TMP/sb/src"
git init -q -b main "$SB_SRC"
printf 'x\n' > "$SB_SRC/requirements.txt"
git -C "$SB_SRC" add requirements.txt
git -C "$SB_SRC" -c user.name=t -c user.email=t@t commit -qm init
git -C "$SB_SRC" branch dev
git clone -q --single-branch "$SB_SRC" "$TMP/sb/sbrepo"
git -C "$TMP/sb/sbrepo" branch -q feat/sb
printf 'TARGET_BRANCH="dev"\n' > "$HOME/.config/wt/sbrepo.conf"
cd "$TMP/sb/sbrepo" || exit 1
err=$("$WT" new --branch feat/sb 2>&1 >/dev/null); rc=$?
expect_eq "Single-Branch-Clone -> Exit 0" "0" "$rc"
if [[ "$err" == *"origin/dev gibt es lokal nicht"* && "$err" == *"Fertig"* ]]; then ok "Single-Branch-Clone: Hinweis statt 'unveraendert'"
else fail "Single-Branch-Clone: Hinweis statt 'unveraendert'" "$err"; fi
cd "$TMP/inj/repo" || exit 1

# Forge-Erkennung: eingetragene und per insteadOf umgeschriebene URL, Gross-/Kleinschreibung
cd "$REPO" || exit 1
git -C "$REPO" config --unset-all url."$REMOTE_BARE".insteadOf
detect() { # url -> $err = stderr von 'wt new --mr 1' (der Fetch scheitert offline, nur stderr zaehlt)
  git -C "$REPO" remote set-url origin "$1"
  err=$(GIT_ALLOW_PROTOCOL="file" "$WT" new --mr 1 2>&1 >/dev/null) || true
}
git -C "$REPO" config url.git@github.com:.insteadOf gh:
detect "gh:x/y"
if [[ "$err" == *"Forge: github"* ]]; then ok "Forge: insteadOf-Kuerzel auf github.com -> github"
else fail "Forge: insteadOf-Kuerzel auf github.com -> github" "$err"; fi
git -C "$REPO" config --unset-all url.git@github.com:.insteadOf
detect "https://GitHub.com/x/y.git"
if [[ "$err" == *"Forge: github"* ]]; then ok "Forge: GitHub.com gross geschrieben -> github"
else fail "Forge: GitHub.com gross geschrieben -> github" "$err"; fi
detect "ssh://git@github.com:22/x/y.git"
if [[ "$err" == *"Forge: github"* ]]; then ok "Forge: ssh://-URL mit Port -> github"
else fail "Forge: ssh://-URL mit Port -> github" "$err"; fi
detect "git@git.example.org:x/y.git"
if [[ "$err" == *"Forge: gitlab"* ]]; then ok "Forge: selbst gehosteter Host -> gitlab"
else fail "Forge: selbst gehosteter Host -> gitlab" "$err"; fi
detect "git@github.com.evil.example:x/y.git"
if [[ "$err" == *"Forge: gitlab"* ]]; then ok "Forge: github.com nur als Host-Praefix -> gitlab"
else fail "Forge: github.com nur als Host-Praefix -> gitlab" "$err"; fi
git -C "$REPO" remote set-url origin "$REMOTE_BARE"

# TARGET_BRANCH leer, origin/HEAD fehlt und der Remote ist nicht erreichbar -> Hinweise, aber Exit 0
R3="$TMP/repos/r3"
git clone -q "$REMOTE_BARE" "$R3"
git -C "$R3" branch -q feat/loc origin/feat/a
git -C "$R3" symbolic-ref -d refs/remotes/origin/HEAD
git -C "$R3" remote set-url origin "$TMP/gibtsnicht.git"
: > "$R3/requirements.txt"
cd "$R3" || exit 1
err=$("$WT" new --branch feat/loc 2>&1 >/dev/null); rc=$?
expect_eq "new: Zielbranch unbekannt -> Exit 0" "0" "$rc"
if [[ "$err" == *"Default-Branch nicht ermittelbar"*"Zielbranch unbekannt"*"Fertig"* ]]; then ok "new: Zielbranch unbekannt -> Hinweise statt Abbruch"
else fail "new: Zielbranch unbekannt -> Hinweise statt Abbruch" "$err"; fi

# ungueltige Nummer: Fehler vor jedem Netzzugriff (origin/HEAD fehlt hier -> set-head waere sonst der erste Schritt)
err=$("$WT" new --pr abc 2>&1 >/dev/null); rc=$?
expect_eq "new --pr abc -> Exit 1" "1" "$rc"
if [[ "$err" == *"--mr/--pr erwartet eine Nummer"* && "$err" != *"set-head"* ]]; then ok "new --pr abc -> Fehler vor dem Netzzugriff"
else fail "new --pr abc -> Fehler vor dem Netzzugriff" "$err"; fi

# ---------- WT_PREFIX: Repo-Kuerzel vor dem Worktree-Ordner ----------
PX="$TMP/px/pxrepo"; PXB="$TMP/px/pxrepo-worktrees"
git clone -q "$REMOTE_BARE" "$PX"
git -C "$PX" worktree add -q --detach "$PXB/mr-5"      # Ordner ohne Repo-Kuerzel
printf 'WT_PREFIX="mia"\n' > "$HOME/.config/wt/pxrepo.conf"
cd "$PX" || exit 1

err=$("$WT" new --branch feat/a 2>&1 >/dev/null); rc=$?
expect_eq "prefix: new --branch -> Exit 0" "0" "$rc"
if [ -d "$PXB/mia-feat-a" ]; then ok "prefix: new legt mia-feat-a an"; else fail "prefix: new legt mia-feat-a an" "$(ls "$PXB")"; fi
if [[ "$err" != *"kein Repo-Kuerzel"* ]]; then ok "prefix: gesetzt -> keine Erinnerung"; else fail "prefix: gesetzt -> keine Erinnerung" "$err"; fi
for x in feat/a feat-a mia-feat-a; do
  expect_eq "prefix: path $x" "$PXB/mia-feat-a" "$("$WT" path "$x" 2>/dev/null)"
done

err=$("$WT" new --mr 7 2>&1 >/dev/null); rc=$?
expect_eq "prefix: new --mr 7 -> Exit 0" "0" "$rc"
for x in 7 mr-7 mia-mr-7; do
  expect_eq "prefix: path $x" "$PXB/mia-mr-7" "$("$WT" path "$x" 2>/dev/null)"
done

expect_eq "prefix: path mia -> Hauptrepo" "$PX" "$("$WT" path mia 2>/dev/null)"
git -C "$REMOTE_BARE" update-ref refs/heads/mia refs/heads/dev
err=$("$WT" new --branch mia 2>&1 >/dev/null); rc=$?
expect_eq "prefix: new --branch mia (= Repo-Kuerzel) -> Exit 1" "1" "$rc"
if [ ! -e "$PXB/mia-mia" ]; then ok "prefix: new --branch mia legt keinen Ordner an"; else fail "prefix: new --branch mia legt keinen Ordner an" "$err"; fi
expect_eq "prefix: path 5 -> Ordner ohne Repo-Kuerzel" "$PXB/mr-5" "$("$WT" path 5 2>/dev/null)"
err=$("$WT" path 5 2>&1 >/dev/null)
if [[ "$err" == *"worktree move"*"/mr-5"*"/mia-mr-5"* ]]; then ok "prefix: Ordner ohne Repo-Kuerzel -> Umbenennungsbefehl"
else fail "prefix: Ordner ohne Repo-Kuerzel -> Umbenennungsbefehl" "$err"; fi
err=$("$WT" new --mr 5 2>&1 >/dev/null); rc=$?
expect_eq "prefix: new neben Ordner ohne Repo-Kuerzel -> Exit 1" "1" "$rc"
if [[ "$err" == *"ohne Repo-Kuerzel"* ]] && [ ! -e "$PXB/mia-mr-5" ]; then ok "prefix: kein zweiter Ordner fuer MR 5"
else fail "prefix: kein zweiter Ordner fuer MR 5" "$err"; fi

# MR-Nummer aus dem Ordnernamen: ss-Stub meldet Port 8007 belegt -> drop muss abbrechen
mkdir -p "$TMP/ss-stub"
cat > "$TMP/ss-stub/ss" <<'EOF'
#!/usr/bin/env bash
printf 'LISTEN 0 4096 127.0.0.1:8007 0.0.0.0:*\n'
EOF
chmod +x "$TMP/ss-stub/ss"
err=$(PATH="$TMP/ss-stub:$PATH" "$WT" drop mia-mr-7 2>&1 >/dev/null); rc=$?
expect_eq "prefix: drop mia-mr-7 erkennt MR 7 -> Exit 1 bei belegtem Port" "1" "$rc"
if [[ "$err" == *"Port 8007"* ]]; then ok "prefix: drop mia-mr-7 prueft Port 8007"; else fail "prefix: drop mia-mr-7 prueft Port 8007" "$err"; fi
err=$("$WT" drop mia-mr-7 2>&1 >/dev/null); rc=$?
expect_eq "prefix: drop mia-mr-7 -> Exit 0" "0" "$rc"
if [ ! -e "$PXB/mia-mr-7" ]; then ok "prefix: mia-mr-7 entfernt"; else fail "prefix: mia-mr-7 entfernt" "$err"; fi
err=$("$WT" drop 5 2>&1 >/dev/null); rc=$?
expect_eq "prefix: drop 5 (ohne Repo-Kuerzel) -> Exit 0" "0" "$rc"
if [ ! -e "$PXB/mr-5" ] && [[ "$err" != *"worktree move"* ]]; then ok "prefix: drop ohne Umbenennungshinweis"
else fail "prefix: drop ohne Umbenennungshinweis" "$err"; fi

# Erinnerung: ohne WT_PREFIX-Eintrag ja, mit WT_PREFIX="" nicht
RM="$TMP/px/rmrepo"; RMB="$TMP/px/rmrepo-worktrees"
git clone -q "$REMOTE_BARE" "$RM"
cd "$RM" || exit 1
err=$("$WT" new --branch feat/b 2>&1 >/dev/null); rc=$?
expect_eq "prefix: ohne Eintrag -> Exit 0" "0" "$rc"
if [[ "$err" == *"kein Repo-Kuerzel konfiguriert"*'WT_PREFIX=""'* ]] && [ -d "$RMB/feat-b" ]; then ok "prefix: ohne Eintrag -> Erinnerung, Ordner = Slug"
else fail "prefix: ohne Eintrag -> Erinnerung, Ordner = Slug" "$err"; fi
printf 'WT_PREFIX=""\n' > "$HOME/.config/wt/rmrepo.conf"
err=$("$WT" new --branch feat/c 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [[ "$err" != *"kein Repo-Kuerzel"* ]] && [ -d "$RMB/feat-c" ]; then ok "prefix: WT_PREFIX=\"\" -> still, Ordner = Slug"
else fail "prefix: WT_PREFIX=\"\" -> still, Ordner = Slug" "$err"; fi

# Injection ueber die Konfig: der Wert landet in Ordnernamen und run-Strings
printf "WT_PREFIX='mia;touch %s/PWNED'\n" "$TMP" > "$HOME/.config/wt/rmrepo.conf"
err=$("$WT" new --branch feat/a 2>&1 >/dev/null); rc=$?
expect_eq "prefix: WT_PREFIX mit ; -> Exit 1" "1" "$rc"
if [[ "$err" == *"nur Buchstaben und Ziffern"* ]] && [ ! -e "$TMP/PWNED" ]; then ok "prefix: WT_PREFIX mit ; wird nicht ausgefuehrt"
else fail "prefix: WT_PREFIX mit ; wird nicht ausgefuehrt" "$err"; fi
rm -f "$HOME/.config/wt/rmrepo.conf"

# ---------- Namen, die mit dem Repo-Kuerzel oder mit mr- beginnen ----------
git -C "$REMOTE_BARE" update-ref refs/heads/mia-fix refs/heads/dev
git -C "$REMOTE_BARE" update-ref refs/heads/123 refs/heads/dev
git -C "$REMOTE_BARE" update-ref refs/heads/mr/123 refs/heads/dev
git -C "$REMOTE_BARE" update-ref refs/merge-requests/123/head refs/heads/dev

# Branch mit Repo-Kuerzel am Anfang: sein Ordner (mia-mia-fix) waere von dem des Branchs 'fix' nicht zu unterscheiden
cd "$PX" || exit 1
err=$("$WT" new --branch mia-fix 2>&1 >/dev/null); rc=$?
expect_eq "prefix: new --branch mia-fix -> Exit 1" "1" "$rc"
if [[ "$err" == *"Repo-Kuerzel"* && ! -e "$PXB/mia-mia-fix" && ! -e "$PXB/mia-fix" ]]; then ok "prefix: Branch mit Repo-Kuerzel am Anfang wird verweigert"
else fail "prefix: Branch mit Repo-Kuerzel am Anfang wird verweigert" "$err | $(ls "$PXB")"; fi

# Branch 123 / mr/123 ergibt denselben Ordner wie --mr 123 (auch ohne Repo-Kuerzel)
cd "$RM" || exit 1
for b in 123 mr/123; do
  err=$("$WT" new --branch "$b" 2>&1 >/dev/null); rc=$?
  expect_eq "mr-Slug: new --branch $b -> Exit 1" "1" "$rc"
  if [ ! -e "$RMB/mr-123" ]; then ok "mr-Slug: --branch $b legt keinen Ordner mr-123 an"
  else fail "mr-Slug: --branch $b legt keinen Ordner mr-123 an" "$err"; fi
  rm -rf "${RMB:?}/mr-123"; git -C "$RM" worktree prune
done

# Ein Repo-Kuerzel aus der Umgebung zaehlt nicht, nur die Konfig
err=$(WT_PREFIX=mia "$WT" new --branch feat/a 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [ -d "$RMB/feat-a" ] && [ ! -e "$RMB/mia-feat-a" ]; then ok "prefix: WT_PREFIX aus der Umgebung wird ignoriert"
else fail "prefix: WT_PREFIX aus der Umgebung wird ignoriert" "rc=$rc $err"; fi

# ---------- drop --db: die Nummer kommt aus dem Ordnernamen, nicht aus der Eingabe ----------
mkdir -p "$TMP/docker-stub" "$PX/media"
cat > "$TMP/docker-stub/docker" <<'EOF'
#!/usr/bin/env bash
# Stub: Aufruf merken; die DB-Liste kommt aus $DB_EXISTING, createdb scheitert mit $DOCKER_FAIL_CREATEDB
printf '%s\n' "$*" >> "$DOCKER_LOG"
case "$*" in
  *pg_database*) [ -z "${DOCKER_FAIL_PSQL:-}" ] || exit 1; for d in ${DB_EXISTING:-}; do printf '%s\n' "$d"; done ;;
  *createdb*)    [ -z "${DOCKER_FAIL_CREATEDB:-}" ] || exit 1 ;;
esac
EOF
chmod +x "$TMP/docker-stub/docker"
export DOCKER_LOG="$TMP/docker.log"
printf 'WT_PREFIX="mia"\nDB_CONTAINER="stubdb"\nLINK_DIRS=(media)\n' > "$HOME/.config/wt/pxrepo.conf"
cd "$PX" || exit 1
"$WT" new --mr 123 >/dev/null 2>&1
git -C "$PX" worktree add -q -b mia-123 "$PXB/mia-mia-123"   # Branch-Worktree, dessen Name wie ein MR mit Repo-Kuerzel aussieht
: > "$DOCKER_LOG"
PATH="$TMP/docker-stub:$PATH" "$WT" drop mia-123 --db >/dev/null 2>&1; rc=$?
expect_eq "drop mia-123 --db (Branch-Worktree) -> Exit 0" "0" "$rc"
if [ ! -e "$PXB/mia-mia-123" ] && ! grep -q 'review_123' "$DOCKER_LOG"; then ok "drop mia-123 --db loescht nicht die DB-Kopie von MR 123"
else fail "drop mia-123 --db loescht nicht die DB-Kopie von MR 123" "$(cat "$DOCKER_LOG") | $(ls "$PXB")"; fi
DB_EXISTING=review_123 PATH="$TMP/docker-stub:$PATH" "$WT" drop mia-mr-123 --db >/dev/null 2>&1
if grep -q 'dropdb.*review_123' "$DOCKER_LOG"; then ok "drop mia-mr-123 --db loescht review_123 (Positivkontrolle)"
else fail "drop mia-mr-123 --db loescht review_123 (Positivkontrolle)" "$(cat "$DOCKER_LOG")"; fi

# ---------- wt setup: bestehenden Worktree nachtraeglich einrichten ----------
dk() { PATH="$TMP/docker-stub:$PATH" "$WT" "$@"; }   # wt mit Docker-Stub
printf '%s\n' '.env' >> "$PX/.git/info/exclude"   # wie im echten Projekt gitignoriert
printf 'haupt\n' > "$PX/.env"
cat > "$HOME/.config/wt/pxrepo.conf" <<'EOF'
WT_PREFIX="mia"
COPY_FILES=(".env")
LINK_DIRS=(media)
DB_CONTAINER="stubdb"
DB_TEMPLATE="stamm_db"
DB_COPY_PREFIX="review_"
SETTINGS_SHIM_PATH="app/settings_review.py"
SETTINGS_SHIM_IMPORT="app.settings_docker"
EOF
SP="$TMP/px/mein feature"   # fremder Ort, Leerzeichen im Pfad (wie ein PyCharm-Ordner)
git -C "$PX" worktree add -q -b feat/setup "$SP"
mkdir -p "$SP/app"
err=$(dk setup feat/setup 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [ "$(cat "$SP/.env" 2>/dev/null)" = "haupt" ] && [ -L "$SP/media" ]; then ok "setup <branch, Pfad mit Leerzeichen> kopiert .env und verlinkt media"
else fail "setup <branch, Pfad mit Leerzeichen> kopiert .env und verlinkt media" "rc=$rc $err"; fi
printf 'eigen\n' > "$SP/.env"
err=$(dk setup feat/setup 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [[ "$err" == *"schon vorhanden"* ]] && [[ "$err" != *"> cp "* ]] && [[ "$err" != *"> ln "* ]]; then ok "setup zweimal -> nur 'schon vorhanden', kein cp/ln"
else fail "setup zweimal -> nur 'schon vorhanden', kein cp/ln" "rc=$rc $err"; fi
expect_eq "setup ueberschreibt eine vorhandene .env nie" "eigen" "$(cat "$SP/.env")"
cd "$SP/app" || exit 1
dk setup . >/dev/null 2>&1; rc=$?
expect_eq "setup . aus einem Unterordner -> Exit 0" "0" "$rc"
cd "$PX" || exit 1
err=$(dk setup @ 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [[ "$err" == *"Quelle"* ]]; then ok "setup @ -> verweigert (Hauptordner ist die Quelle)"; else fail "setup @ -> verweigert (Hauptordner ist die Quelle)" "rc=$rc $err"; fi

git -C "$PX" worktree add -q -b feat/x "$PXB/mia-feat-x"
: > "$DOCKER_LOG"
err=$(dk setup mia-feat-x --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -q 'createdb -U postgres -T stamm_db review_feat_x' "$DOCKER_LOG" \
   && grep -q "NAME'\] = 'review_feat_x'" "$PXB/mia-feat-x/app/settings_review.py"; then ok "setup <ordner> --db -> Kopie review_feat_x und Shim"
else fail "setup <ordner> --db -> Kopie review_feat_x und Shim" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
: > "$DOCKER_LOG"
err=$(DB_EXISTING=review_feat_x dk setup mia-feat-x --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && ! grep -q createdb "$DOCKER_LOG" && [[ "$err" == *"schon vorhanden"* ]]; then ok "setup --db zweimal -> DB und Shim schon vorhanden"
else fail "setup --db zweimal -> DB und Shim schon vorhanden" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
git -C "$PX" worktree add -q -b feat_x "$PXB/mia-feat_x"   # ergibt denselben DB-Namen wie mia-feat-x
: > "$DOCKER_LOG"
err=$(DB_EXISTING=review_feat_x dk setup mia-feat_x --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && ! grep -q createdb "$DOCKER_LOG" && [ ! -e "$PXB/mia-feat_x/app/settings_review.py" ]; then ok "setup --db: fremde DB gleichen Namens -> Abbruch, nie mitbenutzen"
else fail "setup --db: fremde DB gleichen Namens -> Abbruch, nie mitbenutzen" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
LONG="mia-$(printf 'x%.0s' $(seq 1 60))"
git -C "$PX" worktree add -q -b feat/lang "$PXB/$LONG"
err=$(dk setup "$LONG" --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [[ "$err" == *"63"* ]]; then ok "setup --db: DB-Name ueber 63 Bytes -> Abbruch"; else fail "setup --db: DB-Name ueber 63 Bytes -> Abbruch" "rc=$rc $err"; fi
: > "$DOCKER_LOG"
err=$(DOCKER_FAIL_CREATEDB=1 dk setup mia-feat_x --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [[ "$err" == *"Server auf der Haupt-DB"* ]]; then ok "createdb scheitert -> Hinweis auf Server an der Haupt-DB"
else fail "createdb scheitert -> Hinweis auf Server an der Haupt-DB" "rc=$rc $err"; fi
: > "$DOCKER_LOG"
err=$(dk new --branch feat/c --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -q 'createdb .*review_feat_c' "$DOCKER_LOG"; then ok "new --branch --db -> Kopie review_feat_c"; else fail "new --branch --db -> Kopie review_feat_c" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
sed -i "s/'review_feat_x'/'review_custom'/" "$PXB/mia-feat-x/app/settings_review.py"
: > "$DOCKER_LOG"
DB_EXISTING="review_custom review_feat_x" dk drop mia-feat-x --db --force >/dev/null 2>&1
if grep -q 'dropdb .*review_custom' "$DOCKER_LOG" && ! grep -q 'dropdb .*review_feat_x' "$DOCKER_LOG"; then ok "drop --db loescht die DB aus dem Shim"
else fail "drop --db loescht die DB aus dem Shim" "$(cat "$DOCKER_LOG")"; fi
: > "$DOCKER_LOG"
err=$(DB_EXISTING=review_feat_x dk drop feat_x --db --force 2>&1 >/dev/null)
if ! grep -q dropdb "$DOCKER_LOG" && [[ "$err" == *"dropdb"* ]]; then ok "drop --db ohne Shim (Branch-Ordner) -> fremde Kopie gleichen Namens bleibt, Befehl nur als Hinweis"
else fail "drop --db ohne Shim (Branch-Ordner) -> fremde Kopie gleichen Namens bleibt, Befehl nur als Hinweis" "$(cat "$DOCKER_LOG") $err"; fi
# Shim zeigt auf die Vorlage (von Hand angepasst oder aus dem Hauptordner kopiert): nie als Kopie behandeln
git -C "$PX" worktree add -q -b feat/tpl "$PXB/mia-feat-tpl"; mkdir -p "$PXB/mia-feat-tpl/app"
printf "from app.settings_docker import *\nDATABASES['default']['NAME'] = 'stamm_db'\n" > "$PXB/mia-feat-tpl/app/settings_review.py"
: > "$DOCKER_LOG"
err=$(DB_EXISTING=stamm_db dk setup mia-feat-tpl --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [[ "$err" == *"stamm_db"*"keine DB-Kopie"* ]]; then ok "setup --db: Shim zeigt auf DB_TEMPLATE -> Abbruch"; else fail "setup --db: Shim zeigt auf DB_TEMPLATE -> Abbruch" "rc=$rc $err"; fi
err=$(DB_EXISTING=stamm_db dk drop mia-feat-tpl --db --force 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && ! grep -q dropdb "$DOCKER_LOG" && [ -d "$PXB/mia-feat-tpl" ]; then ok "drop --db: Shim zeigt auf DB_TEMPLATE -> Abbruch vor allem, Haupt-DB bleibt"
else fail "drop --db: Shim zeigt auf DB_TEMPLATE -> Abbruch vor allem, Haupt-DB bleibt" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
printf "from app.settings_docker import *\nDATABASES['default']['NAME'] = 'andere_db'\n" > "$PXB/mia-feat-tpl/app/settings_review.py"
: > "$DOCKER_LOG"
err=$(DB_EXISTING=andere_db dk drop mia-feat-tpl --db --force 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && ! grep -q dropdb "$DOCKER_LOG"; then ok "drop --db: Shim-Name ohne DB_COPY_PREFIX -> Abbruch"; else fail "drop --db: Shim-Name ohne DB_COPY_PREFIX -> Abbruch" "rc=$rc $(cat "$DOCKER_LOG") $err"; fi
git -C "$PX" worktree remove --force "$PXB/mia-feat-tpl"
# Container nicht erreichbar: vor dem Entfernen pruefen, sonst geht der DB-Name mit dem Shim verloren
git -C "$PX" worktree add -q -b feat/down "$PXB/mia-feat-down"
dk setup mia-feat-down --db >/dev/null 2>&1
err=$(DOCKER_FAIL_PSQL=1 dk drop mia-feat-down --db --force 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [ -d "$PXB/mia-feat-down" ]; then ok "drop --db: Container nicht erreichbar -> Abbruch, Worktree bleibt"; else fail "drop --db: Container nicht erreichbar -> Abbruch, Worktree bleibt" "rc=$rc $err"; fi
git -C "$PX" worktree remove --force "$PXB/mia-feat-down"
# Shim als haengender Symlink: nie hindurchschreiben
git -C "$PX" worktree add -q -b feat/sym "$PXB/mia-feat-sym"; mkdir -p "$PXB/mia-feat-sym/app"
mkdir -p "$TMP/ausserhalb"; ln -s "$TMP/ausserhalb/shim.py" "$PXB/mia-feat-sym/app/settings_review.py"
dk setup mia-feat-sym --db >/dev/null 2>&1
if [ ! -e "$TMP/ausserhalb/shim.py" ]; then ok "setup --db schreibt nicht durch einen haengenden Symlink"; else fail "setup --db schreibt nicht durch einen haengenden Symlink" "Datei ausserhalb angelegt"; fi
git -C "$PX" worktree remove --force "$PXB/mia-feat-sym"
# new --db: DB-Probleme vor dem Anlegen erkennen, nicht danach
: > "$DOCKER_LOG"
err=$(DB_EXISTING=review_feat_b dk new --branch feat/b --db 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [ ! -e "$PXB/mia-feat-b" ] && ! grep -q createdb "$DOCKER_LOG"; then ok "new --branch --db: DB-Name schon vergeben -> Abbruch vor dem Anlegen"
else fail "new --branch --db: DB-Name schon vergeben -> Abbruch vor dem Anlegen" "rc=$rc $(ls "$PXB") $err"; fi
# Abschlusshinweis von wt new: RUN_HINT nur mit DB-Kopie, sonst wt run (RUN_HINT nennt den Shim)
printf 'RUN_HINT="python manage.py runserver 127.0.0.1:{port} --settings=app.settings_review"\n' >> "$HOME/.config/wt/pxrepo.conf"
err=$(dk new --mr 123 2>&1 >/dev/null)
if [[ "$err" == *"wt run 123"* ]] && [[ "$err" != *"--settings=app.settings_review"* ]]; then ok "new --mr ohne --db -> Hinweis wt run, kein RUN_HINT mit fehlendem Shim"
else fail "new --mr ohne --db -> Hinweis wt run, kein RUN_HINT mit fehlendem Shim" "$err"; fi
dk drop 123 --force >/dev/null 2>&1
err=$(dk new --mr 123 --db 2>&1 >/dev/null)
if [[ "$err" == *"runserver 127.0.0.1:8123 --settings=app.settings_review"* ]]; then ok "new --mr --db -> RUN_HINT mit Port"
else fail "new --mr --db -> RUN_HINT mit Port" "$err"; fi
DB_EXISTING=review_123 dk drop 123 --db --force >/dev/null 2>&1
err=$("$WT" link 42 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 1 ] && [[ "$err" == *"wt setup"* ]]; then ok "link -> Wegweiser auf wt setup"; else fail "link -> Wegweiser auf wt setup" "rc=$rc $err"; fi
for w in "$SP" "$PXB/$LONG" "$PXB/mia-feat-c"; do git -C "$PX" worktree remove --force "$w"; done
printf 'WT_PREFIX="mia"\nDB_CONTAINER="stubdb"\nLINK_DIRS=(media)\n' > "$HOME/.config/wt/pxrepo.conf"

# run: der Port kommt aus dem gefundenen Ordner - 'mia-123' (Branch-Worktree) ist kein MR
mkdir -p "$TMP/python-stub"
cat > "$TMP/python-stub/python" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" > "$PY_LOG"
EOF
chmod +x "$TMP/python-stub/python"; export PY_LOG="$TMP/py.log"
printf 'x' > "$PX/manage.py"
git -C "$PX" worktree add -q -b mia-77 "$PXB/mia-mia-77"
git -C "$PX" worktree add -q --detach "$PXB/mia-mr-77"
printf 'x' > "$PXB/mia-mia-77/manage.py"; printf 'x' > "$PXB/mia-mr-77/manage.py"
pyrun() { : > "$PY_LOG"; PATH="$TMP/python-stub:$PATH" "$WT" run "$@"; } # stdout/stderr wie wt run, Argumente von manage.py in $PY_LOG
NAMEPORT=$((9000 + $(printf '%s' mia-mia-77 | cksum | cut -d' ' -f1) % 1000))
err=$(pyrun mia-77 runserver 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -Eq "127\.0\.0\.1:$NAMEPORT( |$)" "$PY_LOG"; then ok "run mia-77 (Branch-Worktree) -> fester Port $NAMEPORT aus dem Ordnernamen"
else fail "run mia-77 (Branch-Worktree) -> fester Port $NAMEPORT aus dem Ordnernamen" "rc=$rc $(cat "$PY_LOG") $err"; fi
if [[ "$err" == *"Port $NAMEPORT"*"mia-mia-77"*"--mr"* ]]; then ok "run nennt die Herkunft des Ports und --mr"; else fail "run nennt die Herkunft des Ports und --mr" "$err"; fi
pyrun mia-77 runserver >/dev/null 2>&1; first=$(cat "$PY_LOG")
pyrun mia-77 runserver >/dev/null 2>&1
expect_eq "run mia-77: Port bei jedem Start gleich" "$first" "$(cat "$PY_LOG")"
pyrun mia-77 --mr 813 runserver >/dev/null 2>&1
if grep -q '127.0.0.1:8813' "$PY_LOG" && ! grep -q -- '--mr' "$PY_LOG"; then ok "run --mr 813 -> Port 8813, --mr geht nicht an manage.py"
else fail "run --mr 813 -> Port 8813, --mr geht nicht an manage.py" "$(cat "$PY_LOG")"; fi
pyrun mia-77 --port 9999 --mr 813 runserver >/dev/null 2>&1
if grep -q '127.0.0.1:9999' "$PY_LOG"; then ok "run: --port geht vor --mr"; else fail "run: --port geht vor --mr" "$(cat "$PY_LOG")"; fi
pyrun @ runserver >/dev/null 2>&1
if grep -q '127.0.0.1:8000' "$PY_LOG"; then ok "run @ -> Port 8000 (Hauptordner)"; else fail "run @ -> Port 8000 (Hauptordner)" "$(cat "$PY_LOG")"; fi
err=$(pyrun mia-77 --mr 0813 runserver 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -q '127.0.0.1:8813' "$PY_LOG"; then ok "run --mr 0813 (fuehrende Null) -> Port 8813"; else fail "run --mr 0813 (fuehrende Null) -> Port 8813" "rc=$rc $(cat "$PY_LOG") $err"; fi
err=$(pyrun 77 --mr 813 runserver 2>&1 >/dev/null)
if grep -q '127.0.0.1:8077' "$PY_LOG" && [[ "$err" == *"--mr"*"ignoriert"* ]]; then ok "run 77 --mr 813 -> Ordner gewinnt (8077), --mr als ignoriert gemeldet"
else fail "run 77 --mr 813 -> Ordner gewinnt (8077), --mr als ignoriert gemeldet" "$(cat "$PY_LOG") $err"; fi
printf '#!/usr/bin/env bash\nprintf "LISTEN 0 4096 127.0.0.1:%s 0.0.0.0:*\\n" "%s"\n' "$NAMEPORT" "$NAMEPORT" > "$TMP/ss-stub/ss"
err=$(PATH="$TMP/ss-stub:$PATH" pyrun mia-77 runserver 8001 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -q 'runserver 8001' "$PY_LOG" && [[ "$err" != *"Port $NAMEPORT"* ]]; then ok "run mit eigener Adresse -> kein berechneter Port, keine Belegt-Pruefung darauf"
else fail "run mit eigener Adresse -> kein berechneter Port, keine Belegt-Pruefung darauf" "rc=$rc $(cat "$PY_LOG") $err"; fi

# --mr ohne Nummer: MR zum ausgecheckten Branch suchen (glab/gh als Stub)
mkdir -p "$TMP/forge-stub"
cat > "$TMP/forge-stub/glab" <<'EOF'
#!/usr/bin/env bash
printf 'glab %s\n' "$*" >> "$FORGE_LOG"
[ -n "${GLAB_OUT:-}" ] || exit 1
printf '%s\n' "$GLAB_OUT"
EOF
cat > "$TMP/forge-stub/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$FORGE_LOG"
printf '%s\n' "${GH_OUT:-}"
EOF
chmod +x "$TMP/forge-stub/glab" "$TMP/forge-stub/gh"; export FORGE_LOG="$TMP/forge.log"
fgrun() { : > "$FORGE_LOG"; PATH="$TMP/forge-stub:$PATH" pyrun "$@"; }
err=$(GLAB_OUT=815 fgrun mia-77 --mr runserver 2>&1 >/dev/null)
if grep -q '127.0.0.1:8815' "$PY_LOG" && grep -q -- "mr list --source-branch mia-77 -F json --jq .\[0\].iid" "$FORGE_LOG"; then ok "run --mr (gitlab) findet MR 815 zum Branch -> Port 8815"
else fail "run --mr (gitlab) findet MR 815 zum Branch -> Port 8815" "$(cat "$PY_LOG") | $(cat "$FORGE_LOG") | $err"; fi
err=$(GLAB_OUT="" fgrun mia-77 --mr runserver 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && grep -Eq "127\.0\.0\.1:$NAMEPORT( |$)" "$PY_LOG" && [[ "$err" == *"kein offener MR"* ]]; then ok "run --mr: glab scheitert -> Hinweis, fester Port"
else fail "run --mr: glab scheitert -> Hinweis, fester Port" "rc=$rc $(cat "$PY_LOG") $err"; fi
err=$(GLAB_OUT=null fgrun mia-77 --mr runserver 2>&1 >/dev/null)
if grep -Eq "127\.0\.0\.1:$NAMEPORT( |$)" "$PY_LOG" && [[ "$err" == *"kein offener MR"* ]]; then ok "run --mr: kein MR (null) -> fester Port"
else fail "run --mr: kein MR (null) -> fester Port" "$(cat "$PY_LOG") $err"; fi
NOFORGE="$TMP/noforge-bin"; mkdir -p "$NOFORGE"   # PATH ohne glab und gh - das echte glab darf hier nie laufen
IFS=: read -ra pathdirs <<<"$PATH"
for d in "${pathdirs[@]}"; do for f in "$d"/*; do
  n=${f##*/}; case "$n" in glab|gh) continue ;; esac
  [ -x "$f" ] && [ ! -e "$NOFORGE/$n" ] && ln -s "$f" "$NOFORGE/$n"
done; done
err=$(PATH="$TMP/python-stub:$NOFORGE" "$WT" run mia-77 --mr runserver 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [[ "$err" == *"glab"*"nicht gefunden"* ]] && grep -Eq "127\.0\.0\.1:$NAMEPORT( |$)" "$PY_LOG"; then ok "run --mr ohne glab -> Hinweis, laeuft weiter"
else fail "run --mr ohne glab -> Hinweis, laeuft weiter" "rc=$rc $err"; fi
git -C "$PX" worktree add -q --detach "$TMP/px/irgendwo-detached"; printf 'x' > "$TMP/px/irgendwo-detached/manage.py"
DETPORT=$((9000 + $(printf '%s' irgendwo-detached | cksum | cut -d' ' -f1) % 1000))
err=$(GLAB_OUT=815 fgrun "$TMP/px/irgendwo-detached" --mr runserver 2>&1 >/dev/null)
if grep -Eq "127\.0\.0\.1:$DETPORT( |$)" "$PY_LOG" && [[ "$err" == *"kein Branch"* ]] && [ ! -s "$FORGE_LOG" ]; then ok "run --mr im detached Worktree -> kein Branch, fester Port, keine Abfrage"
else fail "run --mr im detached Worktree -> kein Branch, fester Port, keine Abfrage" "$(cat "$PY_LOG") | $(cat "$FORGE_LOG") | $err"; fi
git -C "$PX" worktree remove "$TMP/px/irgendwo-detached" --force
printf 'WT_PREFIX="mia"\nDB_CONTAINER="stubdb"\nLINK_DIRS=(media)\nFORGE="github"\n' > "$HOME/.config/wt/pxrepo.conf"
GH_OUT=816 fgrun mia-77 --mr runserver >/dev/null 2>&1
if grep -q '127.0.0.1:8816' "$PY_LOG" && grep -q -- "pr list --head mia-77 --json number --jq .\[0\].number" "$FORGE_LOG"; then ok "run --mr (github) findet PR 816 -> Port 8816"
else fail "run --mr (github) findet PR 816 -> Port 8816" "$(cat "$PY_LOG") | $(cat "$FORGE_LOG")"; fi
GH_OUT=816 fgrun mia-77 migrate --mr >/dev/null 2>&1
if [ ! -s "$FORGE_LOG" ]; then ok "run migrate --mr -> keine MR-Abfrage (nur runserver braucht einen Port)"; else fail "run migrate --mr -> keine MR-Abfrage (nur runserver braucht einen Port)" "$(cat "$FORGE_LOG")"; fi

# Settings: mit SETTINGS_SHIM_PATH entscheidet der Shim im Worktree, sonst gilt RUN_SETTINGS wie immer
printf 'WT_PREFIX="mia"\nRUN_SETTINGS="app.settings_review"\n' > "$HOME/.config/wt/pxrepo.conf"
pyrun mia-77 shell >/dev/null 2>&1
if grep -q -- '--settings=app.settings_review' "$PY_LOG"; then ok "run ohne SETTINGS_SHIM_PATH haengt RUN_SETTINGS an (unveraendert)"
else fail "run ohne SETTINGS_SHIM_PATH haengt RUN_SETTINGS an (unveraendert)" "$(cat "$PY_LOG")"; fi
printf 'WT_PREFIX="mia"\nRUN_SETTINGS="app.settings_review"\nSETTINGS_SHIM_PATH="app/settings_review.py"\nSETTINGS_SHIM_IMPORT="app.settings_docker"\nDB_TEMPLATE="stamm_db"\n' > "$HOME/.config/wt/pxrepo.conf"
err=$(pyrun mia-77 shell 2>&1 >/dev/null)
if grep -q -- '--settings=app.settings_docker' "$PY_LOG" && [[ "$err" == *"Haupt-DB"*"stamm_db"* ]]; then ok "run ohne Shim -> SETTINGS_SHIM_IMPORT (Haupt-DB) mit Hinweis"
else fail "run ohne Shim -> SETTINGS_SHIM_IMPORT (Haupt-DB) mit Hinweis" "$(cat "$PY_LOG") $err"; fi
mkdir -p "$PXB/mia-mia-77/app"; printf "from app.settings_docker import *\nDATABASES['default']['NAME'] = 'review_mia_77'\n" > "$PXB/mia-mia-77/app/settings_review.py"
err=$(pyrun mia-77 shell 2>&1 >/dev/null)
if grep -q -- '--settings=app.settings_review' "$PY_LOG" && [[ "$err" == *"review_mia_77"* ]]; then ok "run mit Shim -> RUN_SETTINGS, nennt die DB-Kopie"
else fail "run mit Shim -> RUN_SETTINGS, nennt die DB-Kopie" "$(cat "$PY_LOG") $err"; fi
rm -r "$PXB/mia-mia-77/app"
err=$(pyrun @ migrate 2>&1 >/dev/null)
if [[ "$err" == *"migrate"*"Haupt-DB"*"stamm_db"* ]] && [[ "$err" != *"wt setup"* ]] && grep -q '^manage.py migrate' "$PY_LOG"; then ok "run @ migrate ohne Shim -> deutlicher Haupt-DB-Hinweis, laeuft"
else fail "run @ migrate ohne Shim -> deutlicher Haupt-DB-Hinweis, laeuft" "$(cat "$PY_LOG") $err"; fi
pyrun mia-77 shell --settings=eigene >/dev/null 2>&1
if grep -q -- '--settings=eigene' "$PY_LOG" && ! grep -q 'settings_docker' "$PY_LOG"; then ok "run: eigenes --settings bleibt unangetastet"
else fail "run: eigenes --settings bleibt unangetastet" "$(cat "$PY_LOG")"; fi
mkdir -p "$PXB/mia-mia-77/tief/innen" && cd "$PXB/mia-mia-77/tief/innen" || exit 1
pyrun . shell >/dev/null 2>&1
if grep -q '^manage.py shell' "$PY_LOG"; then ok "run . aus einem Unterordner laeuft im Worktree"; else fail "run . aus einem Unterordner laeuft im Worktree" "$(cat "$PY_LOG")"; fi
cd "$PX" || exit 1
printf 'WT_PREFIX="mia"\nDB_CONTAINER="stubdb"\nLINK_DIRS=(media)\n' > "$HOME/.config/wt/pxrepo.conf"
: > "$PY_LOG"
PATH="$TMP/python-stub:$PATH" "$WT" run 77 runserver >/dev/null 2>&1
if grep -q '127.0.0.1:8077' "$PY_LOG"; then ok "run 77 nimmt Port 8077 aus dem Ordner mia-mr-77"
else fail "run 77 nimmt Port 8077 aus dem Ordner mia-mr-77" "$(cat "$PY_LOG")"; fi

# Kuerzel 'mr' und Ordner ohne Repo-Kuerzel (mr-5): die Nummer geht nicht verloren
MRR="$TMP/px/mrrepo"; MRB="$TMP/px/mrrepo-worktrees"
git clone -q "$REMOTE_BARE" "$MRR"
git -C "$MRR" worktree add -q --detach "$MRB/mr-5"
printf 'WT_PREFIX="mr"\n' > "$HOME/.config/wt/mrrepo.conf"
cd "$MRR" || exit 1
printf '#!/usr/bin/env bash\nprintf "LISTEN 0 4096 127.0.0.1:8005 0.0.0.0:*\\n"\n' > "$TMP/ss-stub/ss"
err=$(PATH="$TMP/ss-stub:$PATH" "$WT" drop 5 2>&1 >/dev/null); rc=$?
expect_eq "prefix mr: drop 5 (Ordner mr-5) -> Exit 1 bei belegtem Port" "1" "$rc"
if [[ "$err" == *"Port 8005"* ]]; then ok "prefix mr: drop 5 findet MR 5 im Ordner mr-5"; else fail "prefix mr: drop 5 findet MR 5 im Ordner mr-5" "$err"; fi

# ---------- Zeichenregeln ----------
cd "$PX" || exit 1
err=$("$WT" setup "a'b" 2>&1 >/dev/null); rc=$?
expect_eq "setup mit ungueltigem Namen -> Exit 1" "1" "$rc"
if [ ! -e "$PXB/a'b" ] && [ ! -e "$PXB/media" ]; then ok "setup mit ungueltigem Namen legt nichts im Sammelordner an"
else fail "setup mit ungueltigem Namen legt nichts im Sammelordner an" "$(ls -A "$PXB")"; fi
cd "$REPO" || exit 1
err=$("$WT" path .. 2>&1 >/dev/null); rc=$?
expect_eq "path .. -> Exit 1" "1" "$rc"
if locale -a 2>/dev/null | grep -qi '^de_DE\.utf-\?8$'; then
  cd "$RM" || exit 1
  err=$(LC_ALL=de_DE.UTF-8 "$WT" new --branch "größe" 2>&1 >/dev/null); rc=$?
  if [ "$rc" -eq 1 ] && [[ "$err" == *"ungewoehnlichen Zeichen"* ]]; then ok "Umlaut im Branchnamen wird unter de_DE.UTF-8 abgelehnt"
  else fail "Umlaut im Branchnamen wird unter de_DE.UTF-8 abgelehnt" "rc=$rc $err"; fi
  err=$(LC_ALL=de_DE.UTF-8 "$WT" new --mr "٣" 2>&1 >/dev/null); rc=$?
  if [ "$rc" -eq 1 ] && [[ "$err" == *"erwartet eine Nummer"* ]]; then ok "fremdes Ziffernzeichen bei --mr wird unter de_DE.UTF-8 abgelehnt"
  else fail "fremdes Ziffernzeichen bei --mr wird unter de_DE.UTF-8 abgelehnt" "rc=$rc $err"; fi
else
  printf 'skip  Locale-Tests: de_DE.UTF-8 ist nicht installiert\n'
fi

# Angriff mit Repo-Kuerzel vorne: nichts wird ausgefuehrt
cd "$PX" || exit 1
"$WT" new --branch "mia-fix;touch $TMP/PWNED3" >/dev/null 2>&1; rc=$?
expect_eq "prefix: Branch mit ; und Repo-Kuerzel -> Exit 1" "1" "$rc"
if [ ! -e "$TMP/PWNED3" ]; then ok "prefix: Branch mit ; und Repo-Kuerzel wird nicht ausgefuehrt"; else fail "prefix: Branch mit ; und Repo-Kuerzel wird nicht ausgefuehrt" "Datei entstanden"; fi

# Abbruch in verschachtelter Subshell: ungueltiger Name darf nicht den Sammelordner liefern
cd "$REPO" || exit 1
rm -f "$IDE_LOG"
"$WT" ide "a'b" >/dev/null 2>&1; rc=$?
expect_eq "ide mit ungueltigem Namen -> Exit 1" "1" "$rc"
sleep 0.5   # open_ide startet per setsid -f, also asynchron
if [ ! -e "$IDE_LOG" ]; then ok "ide mit ungueltigem Namen startet die IDE nicht"; else fail "ide mit ungueltigem Namen startet die IDE nicht" "$(cat "$IDE_LOG")"; fi

printf '\n%s\n' "$([ "$fails" -eq 0 ] && echo 'alle Tests gruen' || echo "$fails Test(s) rot")"
[ "$fails" -eq 0 ]
