#!/usr/bin/env bash
# test_recall.sh - checks sources, actions and the assistant call of recall in a
# throwaway HOME under mktemp. Touches neither real repos nor ~/.config.
#
#   bash dev/recall/test_recall.sh
#
# PATH holds only stubs plus links to basic system tools, so the real fzf,
# bat, wl-copy, notify-send and claude are never called.
set -uo pipefail

RECALL="$(cd "$(dirname "$0")" && pwd)/recall"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home" NO_COLOR=1
mkdir -p "$HOME/.config/recall"

# ---------- system tools (real) and stubs ----------
SYS="$TMP/sysbin"
mkdir -p "$SYS"
for t in bash env cat sed awk sort cut stat realpath basename dirname mkdir \
         printf grep head tail tr jq rm touch ln wc mv; do
  p=$(command -v "$t") || { echo "missing tool for tests: $t"; exit 1; }
  ln -s "$p" "$SYS/$t"
done

STUBS="$TMP/stubs"
mkdir -p "$STUBS"
# fzf stub: call N follows line N of $FZF_SCRIPT:
#   ESC          -> exit 130
#   PICK <text>  -> accept the first line containing <text> (empty query)
#   QUERY <q>    -> enter without a match: print only the query
#   ALT <q>      -> alt-enter with query <q> on the first line
#   ALTNONE <q>  -> alt-enter with query <q> and no match (fzf exits 1)
#   EARLY <text> -> accept after reading only up to the first line containing
#                   <text>, closing the input while the sources still write
# Input lines go to $FZF_IN.<N>, arguments to $FZF_ARGS.<N>.
cat > "$STUBS/fzf" <<'EOF'
#!/usr/bin/env bash
n=$(( $(cat "$FZF_COUNT" 2>/dev/null || echo 0) + 1 ))
printf '%s' "$n" > "$FZF_COUNT"
printf '%s\n' "$@" > "$FZF_ARGS.$n"
step=$(sed -n "${n}p" "$FZF_SCRIPT")
if [ "${step%% *}" = EARLY ]; then
  while IFS= read -r line; do
    case "$line" in *"${step#EARLY }"*) printf '\n\n%s\n' "$line"; exit 0 ;; esac
  done
  exit 1
fi
cat > "$FZF_IN.$n"
case "$step" in
  "PICK "*) line=$(grep -m1 -F -- "${step#PICK }" "$FZF_IN.$n") || exit 1
            printf '\n\n%s\n' "$line" ;;
  "QUERY "*) printf '%s\n' "${step#QUERY }" ;;
  "ALT "*)  printf '%s\nalt-enter\n%s\n' "${step#ALT }" "$(head -n1 "$FZF_IN.$n")" ;;
  "ALTNONE "*) printf '%s\nalt-enter\n' "${step#ALTNONE }"; exit 1 ;;
  *) exit 130 ;;
esac
EOF
cat > "$STUBS/wl-copy" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$CLIP_ARGS"
cat > "$CLIP"
EOF
cat > "$STUBS/notify-send" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$NOTIFY_LOG"
EOF
cat > "$STUBS/bat" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$BAT_LOG"
for last; do :; done
cat "$last"
EOF
# claude stub: logs arguments, working directory and API variables; prints a
# short stream-json answer, or an error result when $CLAUDE_FAIL is set.
cat > "$STUBS/claude" <<'EOF'
#!/usr/bin/env bash
{ printf 'CALL\n'; printf '%s\n' "$@"; printf 'PWD=%s\n' "$PWD"
  printf 'KEY=%s\n' "${ANTHROPIC_API_KEY:-<unset>}"; } >> "$CLAUDE_LOG"
case "${1:-}" in --resume) exit 0 ;; esac
if [ -n "${CLAUDE_FAIL:-}" ]; then
  printf '%s\n' '{"type":"result","is_error":true,"result":"offline"}'
  exit 1
fi
printf '%s\n' '{"type":"system","subtype":"init"}' \
  '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"Hello "}}}' \
  '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"world"}}}' \
  '{"type":"result","is_error":false,"result":"Hello world"}'
EOF
chmod +x "$STUBS"/*
export PATH="$STUBS:$SYS"
export FZF_SCRIPT="$TMP/fzf.script" FZF_COUNT="$TMP/fzf.count" FZF_IN="$TMP/fzf.in" \
       FZF_ARGS="$TMP/fzf.args" CLIP="$TMP/clip" CLIP_ARGS="$TMP/clip.args" \
       NOTIFY_LOG="$TMP/notify.log" BAT_LOG="$TMP/bat.log" CLAUDE_LOG="$TMP/claude.log"

# ---------- fixtures ----------
VAULT="$HOME/Mein Vault"          # space on purpose
mkdir -p "$VAULT/70-resources" "$VAULT/anleitungen" "$VAULT/runbooks"
cat > "$VAULT/70-resources/befehle.md" <<'EOF'
---
title: Befehle
---

# Befehle

Some text with | a pipe outside of a table.

## wt

| Befehl | Erklaerung | Stichworte |
|---|---|---|
| `wt pick` | Worktree aus Liste waehlen | worktree auswahl |
| `git log \| head` | Letzte Commits kurz | verlauf |

## glab

| Befehl | Erklaerung | Stichworte |
| :-- | :-- | :-- |
| glab mr list | Offene MRs | merge request |

| nur | zwei |
|---|---|
| a | b |
EOF
cat > "$VAULT/anleitungen/git-aufraeumen.md" <<'EOF'
---
title: "Git-Branches sicher aufraeumen"
type: knowledge
---
Inhalt Aufraeumen
EOF
printf 'Ohne Frontmatter\n' > "$VAULT/anleitungen/ohne-titel.md"
printf -- '---\ntitle: Index\n---\n' > "$VAULT/anleitungen/_index.md"
printf -- '---\ntitle: Altes Runbook\n---\n' > "$VAULT/runbooks/altes-runbook.md"

R1="$HOME/GitRepos/projekt-a"
mkdir -p "$R1/.reviews" "$HOME/GitRepos/projekt-a-worktrees/mr-1" "$HOME/GitRepos/kein-review"
printf 'alter Text\n' > "$R1/.reviews/alt.txt"
printf 'feat: neu\n\nBody\n' > "$R1/.reviews/commit msg neu.txt"   # space on purpose
printf 'readme\n' > "$R1/.reviews/README.md"
: > "$R1/.reviews/.keep"
touch -d '2026-01-01' "$R1/.reviews/alt.txt"
touch -d '2026-06-01' "$R1/.reviews/commit msg neu.txt"
ln -s "$R1/.reviews" "$HOME/GitRepos/projekt-a-worktrees/mr-1/.reviews"
# A second repo whose .reviews is a symlink to the first: entries must not repeat.
mkdir -p "$HOME/GitRepos/projekt-b"
ln -s "$R1/.reviews" "$HOME/GitRepos/projekt-b/.reviews"
R2="$HOME/PycharmProjects/projekt-c"
mkdir -p "$R2/.reviews"
printf 'mr text\n' > "$R2/.reviews/mr-7.md"
touch -d '2026-03-01' "$R2/.reviews/mr-7.md"

cat > "$HOME/.config/recall/recall.conf" <<EOF
VAULT="$VAULT"
COMMANDS_FILE="\$VAULT/70-resources/befehle.md"
PROCEDURE_GLOBS=("\$VAULT/anleitungen/*.md" "\$VAULT/runbooks/*.md")
EOF

# ---------- mini test framework ----------
fails=0
ok()   { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; fails=$((fails + 1)); }
expect_eq() { # name expected actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1" "expected '$2', got '$3'"; fi
}
expect_has() { # name needle haystack
  if grep -qF -- "$2" <<<"$3"; then ok "$1"; else fail "$1" "missing '$2' in: $3"; fi
}
expect_not() { # name needle haystack
  if grep -qF -- "$2" <<<"$3"; then fail "$1" "unexpected '$2' in: $3"; else ok "$1"; fi
}
reset() { # reset <fzf steps...>
  rm -f "$FZF_COUNT" "$FZF_IN".* "$FZF_ARGS".* "$CLIP" "$CLIP_ARGS" \
        "$NOTIFY_LOG" "$BAT_LOG" "$CLAUDE_LOG"
  printf '%s\n' "$@" > "$FZF_SCRIPT"
}
display() { cut -f3 "$1" | sed 's/\x1b\[[0-9;]*m//g'; } # visible column, without colours

# ---------- help and arguments ----------
out=$("$RECALL" --help 2>&1); rc=$?
expect_eq  "help: exit 0" 0 "$rc"
expect_has "help: names alt-enter" "alt-enter" "$out"
"$RECALL" bogus </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "unknown argument: exit 1" 1 "$rc"

# ---------- sources (seen by fzf) ----------
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq "esc in list: exit 0" 0 "$rc"
list=$(display "$FZF_IN.1")
expect_eq "texts: newest first, README/.keep skipped, symlinks collapsed" \
  "✎ projekt-a · commit msg neu.txt
✎ projekt-c · mr-7.md
✎ projekt-a · alt.txt" "$(grep '^✎' <<<"$list")"
expect_has "commands: backticks stripped"   "⌘ wt pick — Worktree aus Liste waehlen  worktree auswahl wt" "$list"
expect_has "commands: escaped pipe"         "⌘ git log | head — Letzte Commits kurz  verlauf wt" "$list"
expect_has "commands: colon separator row"  "⌘ glab mr list — Offene MRs  merge request glab" "$list"
expect_not "commands: header row skipped"   "⌘ Befehl" "$list"
expect_not "commands: two-column table ignored" "⌘ a" "$list"
expect_eq "procedures: sorted by title, _* skipped, filename fallback" \
  "☰ Altes Runbook
☰ Git-Branches sicher aufraeumen
☰ ohne-titel" "$(grep '^☰' <<<"$list")"
expect_eq "order: texts, commands, procedures" "✎✎✎⌘⌘⌘☰☰☰" \
  "$(awk '{ printf "%s", $1 }' <<<"$list")"
args=$(cat "$FZF_ARGS.1")
expect_has "fzf: shows only the display column" "--with-nth=3" "$args"
expect_has "fzf: enter without match prints the query" "--bind=enter:accept-or-print-query" "$args"

reset ESC
"$RECALL" texts </dev/null >/dev/null 2>&1
expect_eq "recall texts: only texts" "✎✎✎" "$(display "$FZF_IN.1" | awk '{ printf "%s", $1 }')"

# Missing sources are not an error.
mv "$HOME/.config/recall/recall.conf" "$TMP/conf.bak"
cat > "$HOME/.config/recall/recall.conf" <<EOF
VAULT="$TMP/nirgends"
COMMANDS_FILE="\$VAULT/x.md"
PROCEDURE_GLOBS=("\$VAULT/*.md")
TEXT_ROOTS=("$TMP/nirgends")
EOF
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq "empty sources: exit 0" 0 "$rc"
expect_eq "empty sources: empty list" 0 "$(wc -l < "$FZF_IN.1")"
reset "ALT frage" ESC
out=$(printf '\n' | "$RECALL" 2>&1)
expect_has "missing vault: assistant warns" "VAULT not found" "$out"
expect_has "missing vault: assistant runs in HOME" "PWD=$HOME" "$(cat "$CLAUDE_LOG")"
expect_not "missing vault: no --add-dir" "--add-dir" "$(cat "$CLAUDE_LOG")"
mv "$TMP/conf.bak" "$HOME/.config/recall/recall.conf"

# ---------- actions ----------
reset "PICK commit msg neu.txt"
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "text: exit 0 after copy" 0 "$rc"
expect_eq  "text: clipboard holds the file" "$(cat "$R1/.reviews/commit msg neu.txt")" "$(cat "$CLIP")"
expect_has "text: notification" "Copied: commit msg neu.txt" "$(cat "$NOTIFY_LOG")"

reset "EARLY commit msg neu.txt"
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq "early accept: copy still happens" "0 $(cat "$R1/.reviews/commit msg neu.txt")" "$rc $(cat "$CLIP" 2>/dev/null)"

reset "PICK git log"
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "command: clipboard holds the command" "git log | head" "$(cat "$CLIP")"
expect_has "command: copied without newline" "-n" "$(cat "$CLIP_ARGS")"

reset "PICK Git-Branches" ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "procedure: back to the list afterwards" 2 "$(cat "$FZF_COUNT")"
expect_has "procedure: read with pager" "--paging=always" "$(cat "$BAT_LOG")"
expect_has "procedure: the right file" "$VAULT/anleitungen/git-aufraeumen.md" "$(cat "$BAT_LOG")"

# ---------- preview ----------
line=$(grep -F 'wt pick' "$FZF_IN.1")
out=$("$RECALL" --preview "$line" 2>&1)
expect_eq "preview: command" "wt pick

Worktree aus Liste waehlen

keywords: worktree auswahl wt" "$out"
line=$(grep -F 'alt.txt' "$FZF_IN.1")
expect_eq "preview: text via bat" "alter Text" "$("$RECALL" --preview "$line" 2>/dev/null)"

# ---------- assistant ----------
export ANTHROPIC_API_KEY=should-not-reach-claude
reset "QUERY wie raeume ich auf" ESC
out=$(printf '\n' | "$RECALL" 2>&1); rc=$?
expect_eq  "ask (enter, no match): exit 0" 0 "$rc"
log=$(cat "$CLAUDE_LOG")
expect_has "ask: question passed with -p" $'-p\nwie raeume ich auf' "$log"
expect_has "ask: read-only tools" $'--tools\nRead,Grep,Glob' "$log"
expect_has "ask: dontAsk" $'--permission-mode\ndontAsk' "$log"
expect_has "ask: safe mode" "--safe-mode" "$log"
expect_has "ask: sonnet by default" $'--model\nsonnet' "$log"
expect_has "ask: vault as extra dir" $'--add-dir\n'"$VAULT" "$log"
expect_has "ask: runs in the vault" "PWD=$VAULT" "$log"
expect_has "ask: API key removed" "KEY=<unset>" "$log"
expect_has "ask: streamed answer shown" "Hello world" "$out"
expect_has "ask: enter returns to the list with the query" "--query=wie raeume ich auf" "$(cat "$FZF_ARGS.2")"

printf 'ASSIST_MODEL=""\n' >> "$HOME/.config/recall/recall.conf"
reset "ALT frage"
printf '\033' | "$RECALL" >/dev/null 2>&1
expect_not "ask: empty ASSIST_MODEL passes no --model" "--model" "$(cat "$CLAUDE_LOG")"
sed -i '$d' "$HOME/.config/recall/recall.conf"

reset "ALT kurze frage"
printf 'n' | "$RECALL" >/dev/null 2>&1
id=$(grep -A1 -- '--session-id' "$CLAUDE_LOG" | sed -n 2p)
expect_has "ask (alt-enter): n resumes the same session" $'--resume\n'"$id" "$(cat "$CLAUDE_LOG")"
expect_eq  "ask: n leaves the list" 1 "$(cat "$FZF_COUNT")"

reset "ALT frage"
printf '\033' | "$RECALL" >/dev/null 2>&1; rc=$?
expect_eq "ask: esc quits" "0 1" "$rc $(cat "$FZF_COUNT")"

reset "ALTNONE frage ohne treffer"
printf '\033' | "$RECALL" >/dev/null 2>&1
expect_has "ask (alt-enter, no match): assistant is asked" $'-p\nfrage ohne treffer' "$(cat "$CLAUDE_LOG" 2>/dev/null)"

reset "QUERY " ESC
out=$("$RECALL" </dev/null 2>&1)
expect_has "ask: empty question is refused" "type a question first" "$out"
expect_eq  "ask: empty question calls nobody" "" "$(cat "$CLAUDE_LOG" 2>/dev/null)"

reset "ALT frage" ESC
out=$(printf '\n' | CLAUDE_FAIL=1 "$RECALL" 2>&1); rc=$?
expect_has "ask failure: message shown" "Error: offline" "$out"
expect_has "ask failure: exit code named" "exit code 1" "$out"
expect_eq  "ask failure: back to the list" 2 "$(cat "$FZF_COUNT")"
unset ANTHROPIC_API_KEY

# ---------- missing tools ----------
mv "$STUBS/wl-copy" "$TMP/wl-copy.off"
out=$("$RECALL" </dev/null 2>&1); rc=$?
expect_eq  "missing wl-copy: exit 1" 1 "$rc"
expect_has "missing wl-copy: install hint" "sudo dnf install wl-clipboard" "$out"
mv "$TMP/wl-copy.off" "$STUBS/wl-copy"
mv "$STUBS/fzf" "$TMP/fzf.off"
out=$("$RECALL" </dev/null 2>&1)
expect_has "missing fzf: install hint" "sudo dnf install fzf" "$out"
mv "$TMP/fzf.off" "$STUBS/fzf"

mv "$STUBS/claude" "$TMP/claude.off"
reset "ALT frage" ESC
out=$("$RECALL" </dev/null 2>&1); rc=$?
expect_has "missing claude: hint, list keeps working" "'claude' is missing" "$out"
expect_eq  "missing claude: back to the list" "0 2" "$rc $(cat "$FZF_COUNT")"
mv "$TMP/claude.off" "$STUBS/claude"

# ---------- result ----------
if [ "$fails" -eq 0 ]; then printf '\nall tests passed\n'; else printf '\n%s test(s) failed\n' "$fails"; fi
[ "$fails" -eq 0 ]
