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
expect_eq "path . -> Hauptrepo"         "$REPO"            "$("$WT" path . 2>/dev/null)"
expect_eq "path <reponame> -> Hauptrepo" "$REPO"           "$("$WT" path demo 2>/dev/null)"
expect_eq "path main -> Worktree main"  "$BASE/main"       "$("$WT" path main 2>/dev/null)"
expect_eq "path <slug>"                 "$BASE/feature-x"  "$("$WT" path feature-x 2>/dev/null)"
expect_eq "path <branch mit />"         "$BASE/feature-x"  "$("$WT" path feature/x 2>/dev/null)"
expect_eq "path <nr>"                   "$BASE/mr-42"      "$("$WT" path 42 2>/dev/null)"
expect_eq "path <absoluter Pfad>"       "$BASE/mr-42"      "$("$WT" path "$BASE/mr-42" 2>/dev/null)"
cd "$BASE/mr-42" || exit 1
expect_eq "path . aus einem Worktree"   "$REPO"            "$("$WT" path . 2>/dev/null)"
if "$WT" path gibtsnicht >/dev/null 2>&1; then fail "path unbekannt" "Exit 0"; else ok "path unbekannt -> Fehler"; fi

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
err=$("$WT" path . 2>&1 >/dev/null)
if [[ "$err" != *"TARGET_BRANCH"* ]]; then ok "Hauptordner auf dev -> keine Warnung"
else fail "Hauptordner auf dev -> keine Warnung" "$err"; fi
git -C "$REPO" switch -q -c anderes
err=$("$WT" path . 2>&1 >/dev/null)
if [[ "$err" == *"anderes"*"dev"* ]]; then ok "Hauptordner auf anderem Branch -> Warnung"
else fail "Hauptordner auf anderem Branch -> Warnung" "$err"; fi
git -C "$REPO" switch -q dev
printf 'IDE_CMD="fake-ide"\nTARGET_BRANCH="gibtsnicht"\n' > "$HOME/.config/wt/demo.conf"
err=$("$WT" path . 2>&1 >/dev/null)
if [[ "$err" != *"TARGET_BRANCH"* ]]; then ok "TARGET_BRANCH lokal unbekannt -> keine Warnung"
else fail "TARGET_BRANCH lokal unbekannt -> keine Warnung" "$err"; fi
printf 'IDE_CMD="fake-ide"\n' > "$HOME/.config/wt/demo.conf"

# ---------- wt drop ----------
cd "$REPO" || exit 1
if "$WT" drop . >/dev/null 2>&1; then fail "drop ." "Exit 0"; else ok "drop . -> verweigert"; fi
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

# ---------- WT_PREFIX: Kuerzel vor dem Worktree-Ordner ----------
PX="$TMP/px/pxrepo"; PXB="$TMP/px/pxrepo-worktrees"
git clone -q "$REMOTE_BARE" "$PX"
git -C "$PX" worktree add -q --detach "$PXB/mr-5"      # Ordner von vor dem Kuerzel
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
if [[ "$err" == *"kein Repo-Kuerzel konfiguriert"*'WT_PREFIX=""'* ]] && [ -d "$RMB/feat-b" ]; then ok "prefix: ohne Eintrag -> Erinnerung, Ordner wie bisher"
else fail "prefix: ohne Eintrag -> Erinnerung, Ordner wie bisher" "$err"; fi
printf 'WT_PREFIX=""\n' > "$HOME/.config/wt/rmrepo.conf"
err=$("$WT" new --branch feat/c 2>&1 >/dev/null); rc=$?
if [ "$rc" -eq 0 ] && [[ "$err" != *"kein Repo-Kuerzel"* ]] && [ -d "$RMB/feat-c" ]; then ok "prefix: WT_PREFIX=\"\" -> still, Ordner wie bisher"
else fail "prefix: WT_PREFIX=\"\" -> still, Ordner wie bisher" "$err"; fi

# Injection ueber die Konfig: der Wert landet in Ordnernamen und run-Strings
printf "WT_PREFIX='mia;touch %s/PWNED'\n" "$TMP" > "$HOME/.config/wt/rmrepo.conf"
err=$("$WT" new --branch feat/a 2>&1 >/dev/null); rc=$?
expect_eq "prefix: WT_PREFIX mit ; -> Exit 1" "1" "$rc"
if [[ "$err" == *"nur Buchstaben und Ziffern"* ]] && [ ! -e "$TMP/PWNED" ]; then ok "prefix: WT_PREFIX mit ; wird nicht ausgefuehrt"
else fail "prefix: WT_PREFIX mit ; wird nicht ausgefuehrt" "$err"; fi
rm -f "$HOME/.config/wt/rmrepo.conf"

# Abbruch in verschachtelter Subshell: ungueltiger Name darf nicht den Sammelordner liefern
cd "$REPO" || exit 1
: > "$IDE_LOG"
"$WT" ide "a'b" >/dev/null 2>&1; rc=$?
expect_eq "ide mit ungueltigem Namen -> Exit 1" "1" "$rc"

printf '\n%s\n' "$([ "$fails" -eq 0 ] && echo 'alle Tests gruen' || echo "$fails Test(s) rot")"
[ "$fails" -eq 0 ]
