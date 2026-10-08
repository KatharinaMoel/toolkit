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

export HOME="$TMP/home" NO_COLOR=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
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

printf '\n%s\n' "$([ "$fails" -eq 0 ] && echo 'alle Tests gruen' || echo "$fails Test(s) rot")"
[ "$fails" -eq 0 ]
