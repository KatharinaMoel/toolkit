#!/usr/bin/env bash
# test_recall.sh - checks sources, the grouped list, keys, the text lifecycle,
# actions and the assistant call of recall in a throwaway HOME under mktemp.
# Touches neither real repos, ~/.config nor the real trash.
#
#   bash dev/recall/test_recall.sh
#
# PATH holds only stubs plus links to basic system tools, so the real fzf,
# bat, wl-copy, notify-send, gio and claude are never called.
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
         printf grep head tail tr jq touch ln wc mv mktemp date setsid git sleep cp paste find seq; do
  p=$(command -v "$t") || { echo "missing tool for tests: $t"; exit 1; }
  ln -s "$p" "$SYS/$t"
done
# rm logs its arguments, so the tests can prove that texts are never removed with it.
printf '#!%s\nprintf "%%s\\n" "$*" >> "%s/rm.log"\nexec %s "$@"\n' \
  "$(command -v bash)" "$TMP" "$(command -v rm)" > "$SYS/rm"
chmod +x "$SYS/rm"

STUBS="$TMP/stubs"
mkdir -p "$STUBS"
# fzf stub: call N follows line N of $FZF_SCRIPT:
#   ESC           -> exit 130
#   PICK <text>   -> accept the first line containing <text> (empty query)
#   SEARCH <text> -> type <text>: reload the flat list the way the change
#                    binding does, accept its first line containing <text>
#   QUERY <q>     -> enter without a match: print only the query
#   ALT <q>       -> alt-enter with query <q> on the first line
#   ALTNONE <q>   -> alt-enter with query <q> and no match (fzf exits 1)
#   EARLY <text>  -> accept after reading only up to the first line containing
#                    <text>, while the other view is still built in the background
#   WAITFLAT      -> wait up to 2 s for the background build of the flat list,
#                    note "flat.list ready" in $FZF_IN.<N>.flat, then quit like esc
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
if [ "$step" = WAITFLAT ]; then
  for _ in $(seq 1 40); do [ -s "$RECALL_RUN/flat.list" ] && break; sleep 0.05; done
  [ -s "$RECALL_RUN/flat.list" ] && echo "flat.list ready" > "$FZF_IN.$n.flat"
  exit 130
fi
case "$step" in
  "PICK "*) line=$(grep -m1 -F -- "${step#PICK }" "$FZF_IN.$n") || exit 1
            printf '\n\n%s\n' "$line" ;;
  "SEARCH "*) line=$("$RECALL_BIN" --list flat | grep -m1 -F -- "${step#SEARCH }") || exit 1
              printf '%s\n\n%s\n' "${step#SEARCH }" "$line" ;;
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
cat > "$STUBS/glow" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$GLOW_LOG"
for last; do :; done
printf 'GLOW: '; cat "$last"
EOF
# gio stub: logs the call and moves the file into a fake trash.
cat > "$STUBS/gio" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GIO_LOG"
[ "$1" = trash ] && mv "$2" "$TRASH_DIR/"
EOF
cat > "$STUBS/opener" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$OPEN_LOG"
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
       NOTIFY_LOG="$TMP/notify.log" BAT_LOG="$TMP/bat.log" CLAUDE_LOG="$TMP/claude.log" \
       GLOW_LOG="$TMP/glow.log" GIO_LOG="$TMP/gio.log" OPEN_LOG="$TMP/open.log" \
       TRASH_DIR="$TMP/trash" RECALL_BIN="$RECALL"
mkdir -p "$TRASH_DIR"
cd "$TMP" || exit 1   # no git repo around: the start directory names no repo

# Fixed "now" (2026-06-03 12:00 UTC); fixture dates are relative to it.
export RECALL_NOW=1780488000 TZ=UTC
D=86400
ago() { date -d "@$(( RECALL_NOW - $1 ))" '+%Y-%m-%d %H:%M:%S'; }   # ago <seconds>
STATE="$HOME/.local/state/recall"

# ---------- fixtures ----------
VAULT="$HOME/Mein Vault"          # space on purpose
mkdir -p "$VAULT/70-resources" "$VAULT/anleitungen" "$VAULT/runbooks"
cat > "$VAULT/70-resources/befehle.md" <<'EOF'
---
title: Befehle
---

# Befehle

Some text with | a pipe outside of a table.

## wt — Worktrees

| Befehl | Erklaerung | Stichworte |
|---|---|---|
| `wt pick` | Worktree aus Liste waehlen | worktree auswahl |
| `git log \| head` | Letzte Commits kurz | verlauf |

## glab

| Befehl | Erklaerung | Stichworte |
| :-- | :-- | :-- |
| glab mr list | Offene MRs | merge request |
| tab	bed | Tab in der Zelle | tab |

| nur | zwei |
|---|---|
| a | b |
EOF
cat > "$VAULT/anleitungen/git-aufraeumen.md" <<'EOF'
---
title: "Git-Branches sicher aufraeumen"
type: knowledge
updated: 2026-01-01
---
Inhalt Aufraeumen
EOF
printf 'Ohne Frontmatter\n' > "$VAULT/anleitungen/ohne-titel.md"
printf -- '---\ntitle: Index\n---\n' > "$VAULT/anleitungen/_index.md"
printf -- '---\ntitle: Altes Runbook\ncommand: alt-rb\nupdated: 2026-05-20\n---\n' > "$VAULT/runbooks/altes-runbook.md"

R1="$HOME/GitRepos/projekt-a"
mkdir -p "$R1/.reviews" "$HOME/GitRepos/projekt-a-worktrees/mr-1" "$HOME/GitRepos/kein-review"
printf 'alter Text\n' > "$R1/.reviews/alt.txt"
printf 'feat: neu\n\nBody\n' > "$R1/.reviews/commit msg neu.txt"   # space on purpose
printf 'readme\n' > "$R1/.reviews/README.md"
: > "$R1/.reviews/.keep"
touch -d "$(ago $((3 * D)))" "$R1/.reviews/alt.txt"
touch -d "$(ago $((1 * D)))" "$R1/.reviews/commit msg neu.txt"
ln -s "$R1/.reviews" "$HOME/GitRepos/projekt-a-worktrees/mr-1/.reviews"
# A second repo whose .reviews is a symlink to the first: entries must not repeat.
mkdir -p "$HOME/GitRepos/projekt-b"
ln -s "$R1/.reviews" "$HOME/GitRepos/projekt-b/.reviews"
R2="$HOME/PycharmProjects/projekt-c"
mkdir -p "$R2/.reviews"
printf 'mr text\n' > "$R2/.reviews/mr-7.md"
touch -d "$(ago $((2 * D)))" "$R2/.reviews/mr-7.md"

cat > "$HOME/.config/recall/recall.conf" <<EOF
VAULT="$VAULT"
COMMANDS_FILE="\$VAULT/70-resources/befehle.md"
PROCEDURE_GLOBS=("\$VAULT/anleitungen/*.md" "\$VAULT/runbooks/*.md")
OPEN_CMD="opener --flag"
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
        "$NOTIFY_LOG" "$BAT_LOG" "$CLAUDE_LOG" "$GLOW_LOG" "$GIO_LOG" "$OPEN_LOG" "$TMP/rm.log"
  printf '%s\n' "$@" > "$FZF_SCRIPT"
}
display() { cut -f5 "$1" | sed 's/\x1b\[[0-9;]*m//g'; } # visible column, without colours
RUN="$TMP/run"; mkdir -p "$RUN"
flat() { RECALL_RUN="$RUN" "$RECALL" --list flat > "$TMP/flat"; display "$TMP/flat"; }
tree() { RECALL_RUN="$RUN" "$RECALL" --list tree > "$TMP/tree"; display "$TMP/tree"; }
line_of() { grep -m1 -F -- "$2" "$1"; }   # line_of <list file> <text>: the whole list line

# ---------- help and arguments ----------
out=$("$RECALL" --help 2>&1); rc=$?
expect_eq  "help: exit 0" 0 "$rc"
expect_has "help: names alt-enter" "alt-enter" "$out"
expect_has "help: includes the key help" "f1" "$out"
keys=$("$RECALL" --keys 2>&1); rc=$?
expect_eq  "keys: exit 0" 0 "$rc"
for k in "enter" "alt-enter" "esc" "f1" "q" "n " "recall texts" "tab" "ctrl-o" "ctrl-k" "gio trash --restore" "ctrl-y" "f2" "right-click" "ctrl-shift-c" "alt-space" "… n more"; do
  expect_has "keys: names '$k'" "$k" "$keys"
done
expect_has "keys: names the configured days" "parked 4 days after the copy" "$keys"
expect_has "keys: names the 24-hour rule" "last 24 hours" "$keys"
"$RECALL" bogus </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "unknown argument: exit 1" 1 "$rc"

# ---------- flat list (typing) ----------
list=$(flat)
expect_eq "flat texts: newest first, README/.keep skipped, symlinks collapsed" \
  "✎ projekt-a · commit msg neu.txt
✎ projekt-c · mr-7.md
✎ projekt-a · alt.txt" "$(grep '^✎' <<<"$list")"
expect_has "flat commands: backticks stripped"   "⌘ wt pick — Worktree aus Liste waehlen  worktree auswahl wt" "$list"
expect_has "flat commands: escaped pipe"         "⌘ git log | head — Letzte Commits kurz  verlauf wt" "$list"
expect_has "flat commands: colon separator row"  "⌘ glab mr list — Offene MRs  merge request glab" "$list"
expect_has "flat commands: a tab inside a cell becomes a space" "⌘ tab bed — Tab in der Zelle  tab glab" "$list"
expect_not "flat commands: header row skipped"   "⌘ Befehl" "$list"
expect_not "flat commands: two-column table ignored" "⌘ a" "$list"
expect_not "flat commands: subtitle is not a keyword" "Worktrees" "$list"
expect_eq "flat procedures: sorted by title, _* skipped, filename fallback" \
  "☰ Altes Runbook  /alt-rb
☰ Git-Branches sicher aufraeumen
☰ ohne-titel" "$(grep '^☰' <<<"$list")"
printf 'p:1\n' > "$RUN/open"
expect_has "tree procedures: the command follows the title" "    Altes Runbook  /alt-rb" "$(tree)"
expect_has "colours: tree dims the command too" $'Altes Runbook\033[38;5;240m  /alt-rb\033[0m' \
  "$(env -u NO_COLOR RECALL_RUN="$RUN" "$RECALL" --list tree | cut -f5)"
printf '' > "$RUN/open"
expect_has "colours: a procedure's command is dimmed like keywords" $'Altes Runbook\033[38;5;240m  /alt-rb\033[0m' \
  "$(env -u NO_COLOR RECALL_RUN="$RUN" "$RECALL" --list flat | cut -f5)"
expect_eq "flat order: texts, commands, procedures" "✎✎✎⌘⌘⌘⌘☰☰☰" \
  "$(awk '{ printf "%s", $1 }' <<<"$list")"
expect_eq "flat lines carry their group id" "t:projekt-a c:wt p:0" \
  "$(cut -f3 "$TMP/flat" | sed -n '1p;4p;9p' | paste -sd' ')"
expect_eq "flat lines: each has its own cursor id" "$(wc -l < "$TMP/flat")" "$(cut -f4 "$TMP/flat" | grep '^f:' | sort -u | wc -l)"

# ---------- grouped list (empty search) ----------
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq "esc in list: exit 0" 0 "$rc"
expect_eq "groups: newest repo open, other groups closed" \
  "✎ projekt-a (2) ▾
    commit msg neu.txt
    alt.txt
✎ projekt-c (1) ▸
⌘ wt    Worktrees (2) ▸
⌘ glab (2) ▸
☰ anleitungen (2) ▸
☰ runbooks (1) ▸" "$(display "$FZF_IN.1")"
expect_eq "groups: children carry the group id" "grp t:projekt-a|text t:projekt-a|text t:projekt-a" \
  "$(head -n3 "$FZF_IN.1" | awk -F'\t' '{ printf "%s%s %s", (NR > 1 ? "|" : ""), $1, $3 }')"
args=$(cat "$FZF_ARGS.1")
expect_has "fzf: shows only the display column" "--with-nth=5" "$args"
expect_has "fzf: tracks the cursor id" "--id-nth=4" "$args"
expect_has "groups: cursor starts on the newest text, once" "--bind=load:pos(2)+unbind(load)" "$args"
expect_eq  "groups: a group line is tracked by its group, a child by itself" "t:projekt-a f:$R1/.reviews/commit msg neu.txt" \
  "$(sed -n '1p;2p' "$FZF_IN.1" | cut -f4 | paste -sd'|' | sed 's/|/ /')"
expect_has "fzf: keeps the cursor across reloads" "--track" "$args"
expect_has "fzf: enter decided per line" "--bind=enter:transform(" "$args"
expect_has "fzf: tab folds" "--bind=tab:transform(" "$args"
expect_has "fzf: typing switches the view in the background" "--bind=change:bg-transform(" "$args"
expect_has "fzf: ctrl-k keeps" "--bind=ctrl-k:transform(" "$args"
expect_has "fzf: ctrl-o opens" "--bind=ctrl-o:execute-silent(" "$args"
expect_has "fzf: f1 toggles the help" "f1:execute-silent(" "$args"
# grep -F treats each line of a multi-line needle as its own pattern, so check line by line
expect_has "fzf: footer line 1 names the keys" "--footer=tab fold · enter use · ctrl-y copy · alt-enter ask" "$args"
expect_has "fzf: footer line 2 names the keys" "ctrl-o open · ctrl-k keep · f1 help · f2 list" "$args"

# The repo of the start directory comes first and opens, also from a worktree.
git -C "$R2" init -q 2>/dev/null
mkdir -p "$R2/sub"
reset ESC
(cd "$R2/sub" && "$RECALL" </dev/null >/dev/null 2>&1)
expect_eq "groups: start repo first and open" "✎ projekt-c (1) ▾|    mr-7.md|✎ projekt-a (2) ▸" \
  "$(display "$FZF_IN.1" | head -n3 | paste -sd'|')"
rm -rf "$R2/.git" "$R2/sub"

reset WAITFLAT
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq "background build of the flat list lands while the list is open" "flat.list ready" "$(cat "$FZF_IN.1.flat" 2>/dev/null)"

reset ESC
"$RECALL" texts </dev/null >/dev/null 2>&1
expect_eq "recall texts: only text groups" "✎✎" "$(display "$FZF_IN.1" | grep -v '^ ' | awk '{ printf "%s", $1 }')"

# ---------- keys inside fzf ----------
printf 't:projekt-a\n' > "$RUN/open"; printf 'tree' > "$RUN/view"
glab_line=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '⌘ glab')
out=$(RECALL_RUN="$RUN" "$RECALL" --key tab "$glab_line")
expect_has "tab on a group: reload of the rebuilt tree from the cache" "reload-sync(cat \"\$RECALL_RUN/tree.list\")" "$out"
expect_has "tab on a group: cache holds the opened group" "glab mr list" "$(cut -f5 "$RUN/tree.list")"
expect_has "tab on a group: group opened" "    glab mr list — Offene MRs" "$(tree)"
child=$(line_of "$TMP/tree" "glab mr list")
expect_not "tab on a group: no cursor move needed" "pos(" "$out"
out=$(RECALL_RUN="$RUN" "$RECALL" --key tab "$child")
expect_not "tab on a child: closes its group" "glab mr list" "$(tree)"
n=$(cut -f1,2 "$RUN/tree.list" | grep -nx $'grp\tc:glab' | cut -d: -f1)
expect_has "tab on a child: cursor moves to its group line" "+wait+pos($n)" "$out"
expect_eq  "tab on a child: that line is the group" "⌘ glab (2) ▸" "$(sed -n "${n}p" "$RUN/tree.list" | cut -f5)"
out=$(RECALL_RUN="$RUN" "$RECALL" --key enter "$glab_line")
expect_has "enter on a group: opens it" "glab mr list" "$(tree)"
expect_has "enter on a group: reload instead of accept" "reload-sync(cat \"\$RECALL_RUN/tree.list\")" "$out"
expect_eq  "enter on an entry: accept" "accept-or-print-query" "$(RECALL_RUN="$RUN" "$RECALL" --key enter "$child")"
flatline=$(RECALL_RUN="$RUN" "$RECALL" --list flat | grep -F 'glab mr list')
expect_eq  "enter on a search hit: accept" "accept-or-print-query" \
  "$(FZF_QUERY=glab RECALL_RUN="$RUN" "$RECALL" --key enter "$flatline")"
out=$(FZF_QUERY=glab RECALL_RUN="$RUN" "$RECALL" --key enter "$glab_line")
expect_has "enter typed before the flat list arrived: switch first, then take the best hit" \
  "--list flat)+wait+first+accept-or-print-query" "$out"
expect_has "enter typed before the flat list arrived: synchronous reload" "reload-sync(" "$out"
expect_eq  "enter typed before the flat list arrived: view is flat" "flat" "$(cat "$RUN/view")"
printf 'tree' > "$RUN/view"
expect_has "enter with a query but no hit yet: switch, then ask if still none" \
  "+accept-or-print-query" "$(FZF_QUERY=zzz RECALL_RUN="$RUN" "$RECALL" --key enter "")"
printf 'tree' > "$RUN/view"
expect_eq  "enter without a match: accept, so the query asks the assistant" \
  "accept-or-print-query" "$(RECALL_RUN="$RUN" "$RECALL" --key enter "")"
printf 'flat' > "$RUN/view"
expect_eq  "tab while searching: nothing" "" "$(RECALL_RUN="$RUN" "$RECALL" --key tab "$glab_line")"
printf 'tree' > "$RUN/view"
rm -f "$RUN/flat.list"
( sleep 0.2; RECALL_RUN="$RUN" "$RECALL" --list flat > "$RUN/flat.list" ) &
expect_has "typing while the flat cache is being built: wait for it" "reload-sync(cat \"\$RECALL_RUN/flat.list\")" \
  "$(FZF_QUERY=wt RECALL_RUN="$RUN" "$RECALL" --on-change)"
wait
rm -f "$RUN/flat.list"; printf 'tree' > "$RUN/view"
expect_has "typing with no flat cache at all: build it on the spot" "reload-sync('$RECALL' --list flat)" \
  "$(FZF_QUERY=wt RECALL_RUN="$RUN" "$RECALL" --on-change)"
printf 'tree' > "$RUN/view"
RECALL_RUN="$RUN" "$RECALL" --list flat > "$RUN/flat.list"
expect_has "typing: instant reload from the flat cache" "reload-sync(cat \"\$RECALL_RUN/flat.list\")" \
  "$(FZF_QUERY=wt RECALL_RUN="$RUN" "$RECALL" --on-change)"
expect_eq  "typing more: no second reload" "" "$(FZF_QUERY=wtp RECALL_RUN="$RUN" "$RECALL" --on-change)"
expect_has "empty search: back to the tree" "reload-sync(cat \"\$RECALL_RUN/tree.list\")" "$(FZF_QUERY='' RECALL_RUN="$RUN" "$RECALL" --on-change)"
expect_eq  "view file follows" "tree" "$(cat "$RUN/view")"
expect_eq  "ctrl-k on a command: nothing" "" "$(RECALL_RUN="$RUN" "$RECALL" --key keep "$child")"

# ---------- text lifecycle (fixed now, separate text root) ----------
LC="$TMP/lc"; mkdir -p "$LC/repo/.reviews" "$LC/repo-wt"
ln -s "$LC/repo/.reviews" "$LC/repo-wt/.reviews"
mkdir -p "$STATE"
lc_file() { # lc_file <name> <age in seconds> [<copied ago> [<kept ago>]]; known to recall for 30 days
  printf '%s\n' "$1" > "$LC/repo/.reviews/$1"
  touch -d "$(ago "$2")" "$LC/repo/.reviews/$1"
  printf '%s\t%s\t%s\t%s\n' "$LC/repo/.reviews/$1" "$([ -n "${3:-}" ] && echo $((RECALL_NOW - $3)) || echo 0)" \
    "$([ -n "${4:-}" ] && echo $((RECALL_NOW - $4)) || echo 0)" "$((RECALL_NOW - 30 * D))" >> "$STATE/texts.tsv"
}
H=3600
: > "$STATE/texts.tsv"
lc_file new.txt       $((1 * D))
lc_file unused-6d.txt $((7 * D - H))
lc_file unused-7d.txt $((7 * D + H))
lc_file copied-3d.txt $((10 * D)) $((4 * D - H))
lc_file copied-4d.txt $((10 * D)) $((4 * D + H))
lc_file unused-13d.txt $((14 * D - H))
lc_file due.txt       $((14 * D + H))
lc_file kept.txt      $((20 * D)) "" $((1 * D))
lc_file copied-before-change.txt $((1 * D)) $((5 * D))
cp "$HOME/.config/recall/recall.conf" "$TMP/conf.main"
printf 'TEXT_ROOTS=("%s")\nCOMMANDS_FILE=""\nPROCEDURE_GLOBS=()\n' "$LC" >> "$HOME/.config/recall/recall.conf"

list=$(flat)
state_of() { # active, parked or gone, read from the flat list in $list
  local line
  line=$(grep -F " $1" <<<"$list")
  if [ -z "$line" ]; then echo gone
  elif [[ $line == *parked ]]; then echo parked
  else echo active; fi
}
expect_eq "lifecycle: new text active" active "$(state_of new.txt)"
expect_eq "lifecycle: unused 6.9 days active" active "$(state_of unused-6d.txt)"
expect_eq "lifecycle: unused 7.1 days parked" parked "$(state_of unused-7d.txt)"
expect_eq "lifecycle: copied 3.9 days ago active" active "$(state_of copied-3d.txt)"
expect_eq "lifecycle: copied 4.1 days ago parked" parked "$(state_of copied-4d.txt)"
expect_eq "lifecycle: unused 13.9 days still parked" parked "$(state_of unused-13d.txt)"
expect_eq "lifecycle: unused 14.1 days due, shown as parked until the cleanup" parked "$(state_of due.txt)"
expect_eq "lifecycle: kept yesterday active again" active "$(state_of kept.txt)"
expect_eq "lifecycle: rewritten after the copy counts as fresh" active "$(state_of copied-before-change.txt)"
expect_eq "lifecycle: worktree symlink lists each text once" 1 "$(grep -cF ' new.txt' <<<"$list")"
expect_has "groups: parked texts in their own group" "✎ parked (4) ▸" "$(tree)"

# preview lines
expect_has "preview: active text names the parking day" "active · parked from 2026-06-09" \
  "$("$RECALL" --preview "$(line_of "$TMP/flat" " new.txt")" 2>/dev/null)"
expect_has "preview: parked text names the trash day and the key" \
  "parked since 2026-06-03 · copied 2026-05-30 · trash from 2026-06-10 · ctrl-k keeps it" \
  "$("$RECALL" --preview "$(line_of "$TMP/flat" "copied-4d.txt")" 2>/dev/null)"

# ctrl-k on a parked text brings it back
pline=$(line_of "$TMP/flat" "unused-7d.txt")
printf 'flat' > "$RUN/view"
RECALL_RUN="$RUN" "$RECALL" --list flat > "$RUN/flat.list"
expect_has "ctrl-k: before, the cache shows the text as parked" "unused-7d.txt  parked" "$(cut -f5 "$RUN/flat.list")"
out=$(RECALL_RUN="$RUN" "$RECALL" --key keep "$pline")
expect_has "ctrl-k: reload of the current view" "reload-sync(cat \"\$RECALL_RUN/flat.list\")" "$out"
expect_not "ctrl-k: both caches rebuilt, the kept text is no longer parked" "unused-7d.txt  parked" "$(cut -f5 "$RUN/flat.list")"
expect_has "ctrl-k: the tree cache counts one parked text less" "✎ parked (3) ▸" "$(cut -f5 "$RUN/tree.list")"
list=$(flat)
expect_eq "ctrl-k: parked text active again" active "$(state_of unused-7d.txt)"
expect_has "ctrl-k: stored as kept now" "$LC/repo/.reviews/unused-7d.txt	0	$RECALL_NOW" "$(cat "$STATE/texts.tsv")"
RECALL_RUN="$RUN" "$RECALL" --key keep "$(line_of "$TMP/flat" "copied-4d.txt")" >/dev/null
expect_has "ctrl-k on a copied text: copy time kept, keep time added" \
  "$LC/repo/.reviews/copied-4d.txt	$((RECALL_NOW - 4 * D - H))	$RECALL_NOW	$((RECALL_NOW - 30 * D))" "$(cat "$STATE/texts.tsv")"

# cleanup at start: due text to the trash, by real path, never with rm
printf 'gone\t0\t0\n' > "$TMP/stale-row"; sed "s|^gone|$LC/repo/.reviews/vanished.txt|" "$TMP/stale-row" >> "$STATE/texts.tsv"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "cleanup: exit 0" 0 "$rc"
expect_eq  "cleanup: gio trash with the real path, once" "trash $LC/repo/.reviews/due.txt" "$(cat "$GIO_LOG" 2>/dev/null)"
expect_eq  "cleanup: file moved away" "no" "$([ -e "$LC/repo/.reviews/due.txt" ] && echo yes || echo no)"
expect_has "cleanup: logged" "$LC/repo/.reviews/due.txt" "$(cat "$STATE/trash.log" 2>/dev/null)"
expect_has "cleanup: notification" "moved 1 text(s) to the trash" "$(cat "$NOTIFY_LOG" 2>/dev/null)"
expect_has "cleanup: footer message" "moved 1 text(s) to the trash (f1: list)" "$(cat "$FZF_ARGS.1")"
expect_not "cleanup: rm never touches a text" "$LC/repo" "$(cat "$TMP/rm.log" 2>/dev/null)"
expect_not "cleanup: rows of missing files forgotten" "vanished.txt" "$(cat "$STATE/texts.tsv")"
expect_has "cleanup: other rows kept" "copied-4d.txt" "$(cat "$STATE/texts.tsv")"
export RECALL_RUN="$RUN"; "$RECALL" --toggle-help
expect_has "f1: lists what went to the trash" "$LC/repo/.reviews/due.txt" "$("$RECALL" --preview x 2>/dev/null)"
"$RECALL" --toggle-help; unset RECALL_RUN
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "cleanup: nothing due, nothing trashed" "" "$(cat "$GIO_LOG" 2>/dev/null)"

# a text brought back from the trash gets a fresh clock instead of going straight back
mv "$TRASH_DIR/due.txt" "$LC/repo/.reviews/due.txt"            # keeps its old mtime, like a restore
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "restored text: not trashed again" "" "$(cat "$GIO_LOG" 2>/dev/null)"
list=$(flat)
expect_eq  "restored text: active again" active "$(state_of due.txt)"

# a text root that is away for one start loses no text
lc_file kept2.txt $((20 * D)) "" $((1 * D))
mv "$LC" "$TMP/lc.away"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
mv "$TMP/lc.away" "$LC"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "absent root: nothing trashed when it is back" "" "$(cat "$GIO_LOG" 2>/dev/null)"
expect_eq  "absent root: kept text still there" yes "$([ -e "$LC/repo/.reviews/kept2.txt" ] && echo yes || echo no)"

# first start (no state yet): old texts are new to recall, nothing is trashed
mkdir -p "$TMP/lc2/repo2/.reviews"
printf 'old\n' > "$TMP/lc2/repo2/.reviews/old.txt"
touch -d "$(ago $((60 * D)))" "$TMP/lc2/repo2/.reviews/old.txt"
mv "$STATE/texts.tsv" "$TMP/texts.saved"
printf 'TEXT_ROOTS=("%s")\n' "$TMP/lc2" >> "$HOME/.config/recall/recall.conf"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "first start: an old text is not trashed" "" "$(cat "$GIO_LOG" 2>/dev/null)"
expect_has "first start: recall notes when it first saw the text" \
  "$TMP/lc2/repo2/.reviews/old.txt	0	0	$RECALL_NOW" "$(cat "$STATE/texts.tsv")"
expect_has "first start: listed as active" "✎ repo2 · old.txt" "$(flat)"
reset ESC
RECALL_NOW=$((RECALL_NOW + D)) "$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "first start: a day later still not trashed" "" "$(cat "$GIO_LOG" 2>/dev/null)"
reset ESC
RECALL_NOW=$((RECALL_NOW + 14 * D + H)) "$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "first start: trashed 14 days after recall first saw it" "trash $TMP/lc2/repo2/.reviews/old.txt" "$(cat "$GIO_LOG" 2>/dev/null)"
sed -i '$d' "$HOME/.config/recall/recall.conf"
mv "$TMP/texts.saved" "$STATE/texts.tsv"

# without gio nothing is deleted, and the due text stays visible as parked
lc_file due2.txt $((15 * D))
mv "$STUBS/gio" "$TMP/gio.off"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "no gio: file stays" "yes" "$([ -e "$LC/repo/.reviews/due2.txt" ] && echo yes || echo no)"
expect_has "no gio: footer says so" "'gio' is missing, nothing was deleted" "$(cat "$FZF_ARGS.1")"
list=$(flat)
expect_eq  "no gio: due text listed as parked" parked "$(state_of due2.txt)"
mv "$TMP/gio.off" "$STUBS/gio"

# odd file names: README in any case is skipped, tab or newline in a name is skipped
printf 'x\n' > "$LC/repo/.reviews/readme.md"
printf 'x\n' > "$LC/repo/.reviews/tab	name.txt"
printf 'x\n' > "$LC/repo/.reviews/new
line.txt"
list=$(flat)
expect_has "odd names: the list still works" "✎ repo · new.txt" "$list"
expect_not "readme.md (lower case) is skipped" "readme.md" "$list"
expect_not "a tab in a name is skipped" "name.txt" "$list"
expect_not "a newline in a name is skipped" "line.txt" "$list"
mv "$TMP/conf.main" "$HOME/.config/recall/recall.conf"
rm -f "$STATE/texts.tsv"

# Colours: muted accents when NO_COLOR is unset; the visible text stays the same.
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
plain=$(display "$FZF_IN.1")
expect_has "fzf: NO_COLOR -> --no-color" "--no-color" "$(cat "$FZF_ARGS.1")"
expect_not "colours: plain list carries no escape codes at NO_COLOR" $'\033' "$(cut -f5 "$FZF_IN.1")"
reset ESC
env -u NO_COLOR "$RECALL" </dev/null >/dev/null 2>&1
coloured=$(cut -f5 "$FZF_IN.1")
expect_has "colours: fzf theme passed" "--color=" "$(cat "$FZF_ARGS.1")"
expect_eq  "colours: stripped list equals the plain list" "$plain" "$(display "$FZF_IN.1")"
expect_has "colours: text icon muted green"  $'\033[38;5;108m✎' "$coloured"
expect_has "colours: command icon muted blue" $'\033[38;5;110m⌘' "$coloured"
expect_has "colours: procedure icon muted sand" $'\033[38;5;180m☰' "$coloured"
expect_not "colours: no bright 16-colour codes in the list" $'\033[9' "$coloured"
expect_not "colours: no bold in the list" $'\033[1m' "$coloured"

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
expect_not "empty sources: no start position" "load:pos(2)" "$(cat "$FZF_ARGS.1")"
reset "ALT frage" ESC
out=$(printf '\n' | "$RECALL" 2>&1)
expect_has "missing vault: assistant warns" "VAULT not found" "$out"
expect_has "missing vault: assistant runs in HOME" "PWD=$HOME" "$(cat "$CLAUDE_LOG")"
expect_not "missing vault: no --add-dir" "--add-dir" "$(cat "$CLAUDE_LOG")"
mv "$TMP/conf.bak" "$HOME/.config/recall/recall.conf"

# ---------- actions ----------
reset "PICK ✎ projekt-c" ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "a group line reaching the end of the list: back to the list" "0 2" "$rc $(cat "$FZF_COUNT")"
expect_eq  "a group line reaching the end of the list: nothing copied" "" "$(cat "$CLIP" 2>/dev/null)"

reset "PICK commit msg neu.txt"
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "text: exit 0 after copy" 0 "$rc"
expect_eq  "text: clipboard holds the file" "$(cat "$R1/.reviews/commit msg neu.txt")" "$(cat "$CLIP")"
expect_has "text: notification" "Copied: commit msg neu.txt" "$(cat "$NOTIFY_LOG")"
expect_has "text: copy time stored" "$R1/.reviews/commit msg neu.txt	$RECALL_NOW	0" "$(cat "$STATE/texts.tsv")"
rm -f "$STATE/texts.tsv"

reset "EARLY commit msg neu.txt"
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq "early accept: copy still happens" "0 $(cat "$R1/.reviews/commit msg neu.txt")" "$rc $(cat "$CLIP" 2>/dev/null)"
rm -f "$STATE/texts.tsv"

reset "SEARCH git log"
"$RECALL" </dev/null >/dev/null 2>&1
expect_eq  "command: clipboard holds the command" "git log | head" "$(cat "$CLIP")"
expect_has "command: copied without newline" "-n" "$(cat "$CLIP_ARGS")"

reset "SEARCH Git-Branches" ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "procedure: back to the list afterwards" 2 "$(cat "$FZF_COUNT")"
expect_has "procedure: rendered with glow in a pager" $'-p' "$(cat "$GLOW_LOG")"
expect_has "procedure: the right file" "$VAULT/anleitungen/git-aufraeumen.md" "$(cat "$GLOW_LOG")"

mv "$STUBS/glow" "$TMP/glow.off"
reset "SEARCH Git-Branches" ESC
"$RECALL" </dev/null >/dev/null 2>&1
expect_has "procedure without glow: bat pager" "--paging=always" "$(cat "$BAT_LOG")"
mv "$TMP/glow.off" "$STUBS/glow"

# ctrl-o hands texts and procedures to OPEN_CMD, commands not
flat >/dev/null
reset
"$RECALL" --open "$(line_of "$TMP/flat" "Git-Branches")"
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$OPEN_LOG" ] && break; sleep 0.1; done
expect_eq "ctrl-o: OPEN_CMD with its arguments and the file" \
  "--flag
$VAULT/anleitungen/git-aufraeumen.md" "$(cat "$OPEN_LOG" 2>/dev/null)"
reset
"$RECALL" --open "$(line_of "$TMP/flat" "wt pick")"
sleep 0.3
expect_eq "ctrl-o on a command: nothing" "" "$(cat "$OPEN_LOG" 2>/dev/null)"

# ---------- preview ----------
out=$("$RECALL" --preview "$(line_of "$TMP/flat" "wt pick")" 2>&1)
expect_eq "preview: command" "wt pick

Worktree aus Liste waehlen

keywords: worktree auswahl wt" "$out"
expect_has "preview: .txt text via bat" "alter Text" "$("$RECALL" --preview "$(line_of "$TMP/flat" "alt.txt")" 2>/dev/null)"
out=$("$RECALL" --preview "$(line_of "$TMP/flat" "Git-Branches")" 2>/dev/null)
expect_has "preview: procedure rendered with glow" "GLOW: ---" "$out"
expect_has "preview: procedure older than STALE_DAYS" "updated 2026-01-01 · older than 90 days" "$out"
out=$("$RECALL" --preview "$(line_of "$TMP/flat" "Altes Runbook")" 2>/dev/null)
expect_eq  "preview: recent procedure without a hint" "updated 2026-05-20" "$(head -n1 <<<"$out")"
out=$("$RECALL" --preview "$(line_of "$TMP/flat" "ohne-titel")" 2>/dev/null)
expect_has "preview: no front matter, file date" "(file date)" "$(head -n1 <<<"$out")"
grp=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '⌘ wt')
expect_eq "preview: command group as a cheat sheet" "wt pick
    Worktree aus Liste waehlen
git log | head
    Letzte Commits kurz" "$("$RECALL" --preview "$grp" 2>/dev/null)"
grp=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '✎ projekt-a')
expect_eq "preview: text group lists its files" "projekt-a · commit msg neu.txt
projekt-a · alt.txt" "$("$RECALL" --preview "$grp" 2>/dev/null)"
export RECALL_RUN="$TMP/run2"; mkdir -p "$RECALL_RUN"
"$RECALL" --toggle-help
expect_has "preview: f1 shows the key help" "alt-enter" "$("$RECALL" --preview "$grp" 2>/dev/null)"
"$RECALL" --toggle-help
expect_has "preview: second f1 shows the entry again" "projekt-a · alt.txt" "$("$RECALL" --preview "$grp" 2>/dev/null)"
unset RECALL_RUN

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
expect_has "ask: back with a query, the list starts flat" "⌘ wt pick" "$(display "$FZF_IN.2")"
expect_not "ask: back with a query, the cursor starts on the best match" "load:pos(2)" "$(cat "$FZF_ARGS.2")"

printf 'ASSIST_MODEL=""\n' >> "$HOME/.config/recall/recall.conf"
reset "ALT frage"
printf '\033' | "$RECALL" >/dev/null 2>&1
expect_not "ask: empty ASSIST_MODEL passes no --model" "--model" "$(cat "$CLAUDE_LOG")"
sed -i '$d' "$HOME/.config/recall/recall.conf"

reset "ALT kurze frage"
mkdir -p "$TMP/tmpdir"
printf 'n' | TMPDIR="$TMP/tmpdir" "$RECALL" >/dev/null 2>&1
expect_eq  "ask: n leaves no run directory behind" "" "$(find "$TMP/tmpdir" -mindepth 1 -maxdepth 1)"
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

# ---------- copy and stay open (ctrl-y, right-click) ----------
flat >/dev/null
reset ESC
out=$(RECALL_RUN="$RUN" "$RECALL" --copy "$(line_of "$TMP/flat" "git log | head")" 2>&1); rc=$?
expect_eq  "ctrl-y on a command: exit 0, nothing for fzf to run" "0|" "$rc|$out"
expect_eq  "ctrl-y on a command: clipboard holds the command" "git log | head" "$(cat "$CLIP")"
expect_eq  "ctrl-y on a command: no trailing newline" "-n" "$(cat "$CLIP_ARGS")"
expect_has "ctrl-y on a command: notification" "Copied: git log | head" "$(cat "$NOTIFY_LOG")"
reset ESC
RECALL_RUN="$RUN" "$RECALL" --copy "$(line_of "$TMP/flat" "commit msg neu.txt")" >/dev/null 2>&1
expect_eq  "ctrl-y on a text with a space in its name: file content" \
  "$(cat "$R1/.reviews/commit msg neu.txt")" "$(cat "$CLIP")"
reset ESC
RECALL_RUN="$RUN" "$RECALL" --copy "$(line_of "$TMP/flat" "Altes Runbook")" >/dev/null 2>&1
expect_eq  "ctrl-y on a procedure: nothing copied" "" "$(cat "$CLIP" 2>/dev/null)"
RECALL_RUN="$RUN" "$RECALL" --copy "$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '⌘ glab')" >/dev/null 2>&1
expect_eq  "ctrl-y on a group: nothing copied" "" "$(cat "$CLIP" 2>/dev/null)"
out=$(RECALL_RUN="$RUN" "$RECALL" --copy "" 2>&1); rc=$?
expect_eq  "ctrl-y on an empty list: exit 0, nothing copied" "0||" "$rc|$out|$(cat "$CLIP" 2>/dev/null)"
reset ESC
gone=$(line_of "$TMP/flat" "commit msg neu.txt" | sed 's|commit msg neu.txt|weg.txt|g')
out=$(RECALL_RUN="$RUN" "$RECALL" --copy "$gone" 2>&1); rc=$?
expect_eq  "ctrl-y on a text whose file is gone: exit 0, nothing copied" "0|" "$rc|$(cat "$CLIP" 2>/dev/null)"
expect_has "ctrl-y on a text whose file is gone: notification says so" "Gone: weg.txt" "$(cat "$NOTIFY_LOG" 2>/dev/null)"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
args=$(cat "$FZF_ARGS.1")
expect_has "fzf: ctrl-y copies and stays open" "--bind=ctrl-y:execute-silent(" "$args"
expect_has "fzf: right-click copies and stays open" "--bind=right-click:execute-silent(" "$args"
expect_has "fzf: both call --copy" "--copy {})" "$args"

# ---------- collapse the list (f2) and footer buttons ----------
expect_has "fzf: f2 toggles between collapsed and split preview" \
  "--bind=f2:change-preview-window(right,99%,wrap|right,55%,wrap)" "$args"
expect_has "fzf: footer clicks go to on_key" "--bind=click-footer:transform(" "$args"
expect_has "fzf: recall starts expanded" "--preview-window=right,55%,wrap" "$args"
fclick() { FZF_CLICK_FOOTER_LINE=$1 FZF_CLICK_FOOTER_WORD=$2 RECALL_RUN="$RUN" "$RECALL" --key footer ""; }
expect_eq "footer click on 'list': collapse"   "trigger(f2)"     "$(fclick 2 list)"
expect_eq "footer click on 'f2': collapse"     "trigger(f2)"     "$(fclick 2 f2)"
expect_eq "footer click on 'copy': copy"       "trigger(ctrl-y)" "$(fclick 1 copy)"
expect_eq "footer click on 'ctrl-y': copy"     "trigger(ctrl-y)" "$(fclick 1 ctrl-y)"
expect_eq "footer click on 'help': help"       "trigger(f1)"     "$(fclick 2 help)"
expect_eq "footer click on another word: nothing" "" "$(fclick 1 fold)"
expect_eq "footer click on the cleanup line: nothing" "" "$(fclick 3 list)"
expect_eq "footer click between words: nothing" "" "$(fclick 2 '')"
expect_eq "footer click without a line number: nothing" "" "$(fclick '' list)"

# ---------- recent repos open at start, long groups capped ----------
R4="$HOME/GitRepos/projekt-d"; R5="$HOME/GitRepos/projekt-e"
mkdir -p "$R4/.reviews" "$R5/.reviews"
for i in 1 2 3 4 5 6; do
  printf 'd%s\n' "$i" > "$R4/.reviews/d$i.txt"
  touch -d "$(ago $((i * 3600)))" "$R4/.reviews/d$i.txt"
done
printf 'e1\n' > "$R5/.reviews/e1.txt"; touch -d "$(ago $((20 * 3600)))" "$R5/.reviews/e1.txt"
reset ESC
"$RECALL" </dev/null >/dev/null 2>&1
shown=$(display "$FZF_IN.1")
expect_has "start: the newest repo is open" "✎ projekt-d (6) ▾" "$shown"
expect_has "start: a repo with a text from the last 24 hours is open too" "✎ projekt-e (1) ▾" "$shown"
expect_has "start: a repo whose newest text is 2 days old stays closed" "✎ projekt-c (1) ▸" "$shown"
expect_has "start: a repo whose newest text is exactly 24 hours old stays closed" "✎ projekt-a (2) ▸" "$shown"
expect_has "start: cursor still on the first text of the first group" "--bind=load:pos(2)+unbind(load)" "$(cat "$FZF_ARGS.1")"

tree_d=$(sed -n '/✎ projekt-d/,/✎ projekt-e/p' <<<"$shown")
expect_eq "cap: four newest texts, then '… n more'" "✎ projekt-d (6) ▾
    d1.txt
    d2.txt
    d3.txt
    d4.txt
    … 2 more
✎ projekt-e (1) ▾" "$tree_d"
expect_eq "cap: the more line has its own kind, group and cursor id" $'more\tt:projekt-d\tm:t:projekt-d' \
  "$(grep -F '… 2 more' "$FZF_IN.1" | cut -f1,3,4)"
expect_eq "cap: search still lists every text" 6 \
  "$(RECALL_RUN="$RUN" "$RECALL" --list flat | cut -f5 | grep -c 'projekt-d ·')"

printf 't:projekt-d\n' > "$RUN/open"; : > "$RUN/full"; printf 'tree' > "$RUN/view"
rm -f "$RUN/help"
more=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '… 2 more')
expect_eq "preview of '… more': the whole group" "$(printf 'projekt-d · d%s.txt\n' 1 2 3 4 5 6)" \
  "$(RECALL_RUN="$RUN" "$RECALL" --preview "$more" 2>/dev/null)"
out=$(RECALL_RUN="$RUN" "$RECALL" --key enter "$more")
expect_has "enter on '… more': reload of the tree" "reload-sync(cat \"\$RECALL_RUN/tree.list\")" "$out"
expect_has "enter on '… more': cursor on the first newly shown text" "+wait+pos(6)" "$out"
expect_eq  "enter on '… more': the group is noted as shown in full" "t:projekt-d" "$(cat "$RUN/full")"
expect_eq  "enter on '… more': that line is d5" "    d5.txt" "$(sed -n 6p "$RUN/tree.list" | cut -f5)"
expect_has "enter on '… more': all six shown" "    d6.txt" "$(cut -f5 "$RUN/tree.list")"
expect_not "enter on '… more': no more line" "… " "$(cut -f5 "$RUN/tree.list")"
child=$(grep -F 'd2.txt' "$RUN/tree.list")
RECALL_RUN="$RUN" "$RECALL" --key tab "$child" >/dev/null
expect_eq "tab closes the group and forgets 'full'" "" "$(grep -xF t:projekt-d "$RUN/full" 2>/dev/null)"
printf 't:projekt-d\n' >> "$RUN/open"
more=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '… 2 more')
expect_has "reopened group is capped again" "… 2 more" "$more"
out=$(RECALL_RUN="$RUN" "$RECALL" --key tab "$more")
expect_has "tab on '… more': closes, cursor to the group line" "+wait+pos(1)" "$out"
expect_has "enter on '… more' while typing: switch to flat, take the best hit (guard)" \
  "+wait+first+accept-or-print-query" "$(FZF_QUERY=d RECALL_RUN="$RUN" "$RECALL" --key enter "$more")"
printf 'tree' > "$RUN/view"   # that guard switched the view file to flat
expect_eq  "ctrl-y on '… more': nothing copied (guard)" "" \
  "$(rm -f "$CLIP"; RECALL_RUN="$RUN" "$RECALL" --copy "$more"; cat "$CLIP" 2>/dev/null)"
printf 'TEXT_SHOW_MAX=0\n' >> "$HOME/.config/recall/recall.conf"
printf 't:projekt-d\n' > "$RUN/open"
expect_not "TEXT_SHOW_MAX=0: no cap" "… " "$(RECALL_RUN="$RUN" "$RECALL" --list tree | cut -f5)"
sed -i '$d' "$HOME/.config/recall/recall.conf"
reset "PICK … 2 more" ESC
"$RECALL" </dev/null >/dev/null 2>&1; rc=$?
expect_eq  "double-click on '… more' (plain accept): back to the list, nothing copied" "0 2 " "$rc $(cat "$FZF_COUNT") $(cat "$CLIP" 2>/dev/null)"

# Closing with enter forgets "full" like tab does.
printf 't:projekt-d\n' > "$RUN/open"; : > "$RUN/full"; printf 'tree' > "$RUN/view"
more=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '… 2 more')
RECALL_RUN="$RUN" "$RECALL" --key enter "$more" >/dev/null
grpd=$(grep -F '✎ projekt-d' "$RUN/tree.list")
RECALL_RUN="$RUN" "$RECALL" --key enter "$grpd" >/dev/null
RECALL_RUN="$RUN" "$RECALL" --key enter "$grpd" >/dev/null
expect_has "enter closes, enter reopens: capped again" "… 2 more" "$(cut -f5 "$RUN/tree.list")"

# A kept text sorts back by its date; if the cap would hide it, its group is shown in full.
printf 'd0\n' > "$R4/.reviews/d0.txt"; touch -d "$(ago $((10 * D)))" "$R4/.reviews/d0.txt"
printf 't:projekt-d\nparked\n' > "$RUN/open"; : > "$RUN/full"
pl=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F 'd0.txt')
expect_has "ctrl-k setup: d0 is parked" "parked" "$(cut -f3 <<<"$pl")"
RECALL_RUN="$RUN" "$RECALL" --key keep "$pl" >/dev/null
expect_has "ctrl-k on a parked text: still visible in its capped group" "    d0.txt" "$(cut -f5 "$RUN/tree.list")"
expect_eq  "ctrl-k on a parked text: its group is shown in full" "t:projekt-d" "$(cat "$RUN/full")"

# A malformed TEXT_SHOW_MAX falls back to the default instead of breaking enter.
printf 'TEXT_SHOW_MAX=4x\n' >> "$HOME/.config/recall/recall.conf"
printf 't:projekt-d\n' > "$RUN/open"; : > "$RUN/full"
more=$(RECALL_RUN="$RUN" "$RECALL" --list tree | grep -F '… 3 more')
expect_has "TEXT_SHOW_MAX=4x: enter on '… more' still works" "+wait+pos(6)" \
  "$(RECALL_RUN="$RUN" "$RECALL" --key enter "$more" 2>&1)"
sed -i '$d' "$HOME/.config/recall/recall.conf"
expect_has "double-click on '… more': the list comes back still capped" "… 2 more" "$(display "$FZF_IN.2")"

# ---------- result ----------
if [ "$fails" -eq 0 ]; then printf '\nall tests passed\n'; else printf '\n%s test(s) failed\n' "$fails"; fi
[ "$fails" -eq 0 ]
