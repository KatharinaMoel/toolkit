#!/usr/bin/env bash
# test_skill_show.sh - checks lookup, output and list of skill-show in a
# throwaway HOME and project under mktemp. Touches neither the real ~/.claude
# nor ~/.config.
#
#   bash dev/skill-show/test_skill_show.sh
#
# PATH holds only stubs plus links to basic system tools, so the real fzf and
# bat are never called; stubs for curl, wget and claude log every call, and the
# tests prove those logs stay empty (no network, no model).
set -uo pipefail

SS="$(cd "$(dirname "$0")" && pwd)/skill-show"
TEST_SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
RM=$(command -v rm)
SHELLCHECK=$(command -v shellcheck || true)
TMP=$(mktemp -d)
trap '"$RM" -rf "$TMP"' EXIT

export HOME="$TMP/home" NO_COLOR=1 SKILL_SHOW_MANAGED_DIR="$TMP/etc-claude-code"
unset CLAUDE_CONFIG_DIR SKILL_SHOW_FORCE_TTY
mkdir -p "$HOME/.config/skill-show"

# ---------- system tools (real) and stubs ----------
SYS="$TMP/sysbin"
mkdir -p "$SYS"
for t in bash env cat sed awk sort cut stat realpath readlink basename dirname printf \
         grep head tail tr wc find git od cmp sha256sum mkdir ln chmod id ls seq; do
  p=$(command -v "$t") || { echo "missing tool for tests: $t"; exit 1; }
  ln -s "$p" "$SYS/$t"
done
# jq lives in its own folder, so a test can take it out of PATH.
JQBIN="$TMP/jqbin"
mkdir -p "$JQBIN"
p=$(command -v jq) || { echo "missing tool for tests: jq"; exit 1; }
ln -s "$p" "$JQBIN/jq"

STUBS="$TMP/stubs"
mkdir -p "$STUBS"
# Each stub logs its arguments to $TMP/<name>.log.
for t in fzf bat curl wget claude; do
  printf '#!%s\nprintf "%%s\\n" "$@" >> "%s/%s.log"\n' "$(command -v bash)" "$TMP" "$t" > "$STUBS/$t"
done
chmod +x "$STUBS"/*
export PATH="$STUBS:$JQBIN:$SYS"
cd "$TMP" || exit 1   # no git repo around

# ---------- mini framework ----------
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
run() { # run <args...>: sets RC, OUT, ERR; raw stdout stays in $TMP/out
  "$SS" "$@" > "$TMP/out" 2> "$TMP/err"
  RC=$?
  OUT=$(cat "$TMP/out"); ERR=$(cat "$TMP/err")
}
snapshot() { # checksums of every file skill-show could touch
  find "$HOME" "$TMP/proj" -type f -exec sha256sum {} + 2>/dev/null | sort
}

# ---------- fixtures ----------
mkdir -p "$TMP/proj"
git -C "$TMP/proj" init -q

CH="$HOME/.claude"
put() { mkdir -p "$(dirname "$1")"; printf '%b' "$2" > "$1"; }   # put <file> <content with \n escapes>
put "$CH/skills/alpha/SKILL.md"       '---\nname: alpha\ndescription: Alpha skill\n---\nalpha body\n'
put "$CH/skills/renamed/SKILL.md"     '---\nname: beta\ndescription: Folder and name differ\n---\nbeta body\n'
put "$CH/skills/nofm/SKILL.md"        'no front matter here\n'
put "$CH/skills/quoted/SKILL.md"      '---\nname: "quoted-name"\n---\nquoted body\n'
put "$CH/skills/.trash/old/SKILL.md"  '---\nname: old\n---\ndeleted skill\n'
put "$CH/skills/withextras/SKILL.md"  '---\nname: withextras\n---\nsee REFERENCE.md\n'
put "$CH/skills/withextras/REFERENCE.md" 'reference\n'
put "$CH/skills/withextras/scripts/x.sh" 'echo x\n'
put "$TMP/outside/link skill/SKILL.md" '---\nname: linked\n---\nlinked body\n'   # space on purpose
ln -s "$TMP/outside/link skill" "$CH/skills/linked"
put "$CH/commands/plain.md"   '---\ndescription: plain command\n---\nplain body\n'
put "$CH/commands/alpha.md"   'alpha as a command\n'
put "$CH/commands/crlf.md"    'line one\r\nline two\r\n'
put "$CH/commands/esc.md"     'a backslash sequence \\\\n stays, a tab\there\n'
put "$CH/commands/fakeend.md" 'before\n──── end of /somewhere ────\n──── begin ────\nafter\n'
printf 'no final newline' > "$CH/commands/nonl.md"
: > "$CH/commands/empty.md"
{ printf 'long:'; printf 'x%.0s' $(seq 1 12000); printf '\n'; } > "$CH/commands/long.md"
put "$CH/commands/locked.md"  'unreadable\n'
put "$TMP/proj/.claude/skills/projonly/SKILL.md" '---\nname: projonly\n---\nproject skill\n'
put "$TMP/proj/.claude/commands/projcmd.md"      'project command\n'

BEFORE=$(snapshot)

# ---------- command line ----------
run --help
expect_eq  "--help exits 0" 0 "$RC"
expect_has "--help names the main form" "skill-show <name>" "$OUT"

run --bogus
expect_eq  "unknown option exits 2" 2 "$RC"
expect_has "unknown option prints usage on stderr" "usage" "$ERR"
expect_eq  "unknown option prints nothing on stdout" "" "$OUT"

run alpha beta
expect_eq  "two names exit 2" 2 "$RC"

run --project
expect_eq  "--project without a folder exits 2" 2 "$RC"

run --project "$TMP/does-not-exist" alpha
expect_eq  "--project with a missing folder exits 2" 2 "$RC"

# ---------- name checks ----------
for bad in '../x' 'a/b' 'a:b:c' '' 'ä' 'a:' ':b' '/' 'a b' '..' 'a:..'; do
  run -- "$bad"
  expect_eq "invalid name '$bad' exits 2" 2 "$RC"
  expect_eq "invalid name '$bad' prints nothing on stdout" "" "$OUT"
done
# Under a German locale [A-Za-z] also matches umlauts; the check must not.
LC_ALL=de_DE.utf8 "$SS" ä > /dev/null 2>&1; rc=$?
expect_eq "umlaut refused under de_DE.utf8 too" 2 "$rc"

# ---------- show: byte identity ----------
after_begin() { # everything after the begin line of a raw output file, byte for byte
  local n
  n=$(grep -n -m1 -Fx -- '──── begin ────' "$1" | cut -d: -f1)
  [ -n "$n" ] || return 1
  tail -n +"$((n + 1))" -- "$1"
}
expected_block() { # the file, a newline if it lacks one, then the end line
  cat -- "$1"
  if [ -s "$1" ] && [ "$(tail -c1 -- "$1" | wc -l)" -eq 0 ]; then
    printf '\n──── end of %s (no newline at end of file) ────\n' "$1"
  else
    printf '──── end of %s ────\n' "$1"
  fi
}
for c in plain crlf esc fakeend nonl empty long; do
  f="$CH/commands/$c.md"
  run "$c"
  expect_eq "show $c: exit 0" 0 "$RC"
  if cmp -s <(after_begin "$TMP/out") <(expected_block "$f"); then ok "show $c: block is the file byte for byte"
  else fail "show $c: block is the file byte for byte" "$(after_begin "$TMP/out" | od -c | head -5)"; fi
  "$SS" --raw "$c" > "$TMP/raw" 2>/dev/null
  if cmp -s "$TMP/raw" "$f"; then ok "--raw $c equals the file"; else fail "--raw $c equals the file" "$(od -c "$TMP/raw" | head -3)"; fi
done
run empty
expect_not "empty file: no 'no newline' note" "no newline at end of file" "$OUT"
run nonl
expect_has "file without final newline: the end line says so" "──── end of $CH/commands/nonl.md (no newline at end of file) ────" "$OUT"

# ---------- show: header ----------
run plain
expect_has "header names invocation, kind, group, status" "==> /plain · command · personal · active" "$OUT"
expect_has "header names the file" "    file:    $CH/commands/plain.md" "$OUT"
expect_has "header names the equivalent command" "    > cat '$CH/commands/plain.md'" "$OUT"
expect_not "a command has no more: line" "more:" "$OUT"

run /alpha; slash=$OUT
run alpha
expect_eq  "/alpha and alpha give the same output" "$slash" "$OUT"
expect_has "alpha: the skill wins over the command" "==> /alpha · skill · personal · active" "$OUT"
expect_has "alpha: no extra files" "    more:    none" "$OUT"

run beta
expect_has "beta (name:) finds the renamed skill" "    file:    $CH/skills/renamed/SKILL.md" "$OUT"
run renamed
expect_has "renamed (folder) finds it too" "    file:    $CH/skills/renamed/SKILL.md" "$OUT"
expect_has "the header uses the name: value" "==> /beta · skill" "$OUT"

run nofm
expect_has "SKILL.md without front matter: found by its folder" "    file:    $CH/skills/nofm/SKILL.md" "$OUT"
run quoted-name
expect_has "name: in quotes: found without them" "==> /quoted-name · skill" "$OUT"

run linked
expect_has "symlinked skill folder: file under .claude" "    file:    $CH/skills/linked/SKILL.md" "$OUT"
expect_has "symlinked skill folder: link: names the real path" "    link:    $TMP/outside/link skill/SKILL.md" "$OUT"
expect_has "path with a space is quoted in the cat line" "    > cat '$CH/skills/linked/SKILL.md'" "$OUT"
run plain
expect_not "no link: without a symlink" "link:" "$OUT"

run withextras
expect_has "more: lists the other files, sorted, full paths" \
  "$(printf '    more:    %s\n             %s' "$CH/skills/withextras/REFERENCE.md" "$CH/skills/withextras/scripts/x.sh")" "$OUT"

run old
expect_eq  "a skill in .trash is never found" 1 "$RC"
expect_eq  "not found prints nothing on stdout" "" "$OUT"

# ---------- show: --path, project, unreadable ----------
run plain --path
expect_eq  "--path prints exactly the path" "$CH/commands/plain.md" "$OUT"

(cd "$TMP/proj" && "$SS" projonly > "$TMP/out" 2>/dev/null); OUT=$(cat "$TMP/out")
expect_has "project skill found from inside the project" "==> /projonly · skill · project · active" "$OUT"
run projcmd --project "$TMP/proj"
expect_has "--project finds a project command from outside" "==> /projcmd · command · project · active" "$OUT"
run projcmd
expect_eq  "outside the project, its command is not found" 1 "$RC"

if [ "$(id -u)" -ne 0 ]; then
  chmod 000 "$CH/commands/locked.md"
  run locked
  "$SS" --raw locked > /dev/null 2>&1; raw_rc=$?
  chmod 644 "$CH/commands/locked.md"
  expect_eq  "unreadable file with --raw exits 1" 1 "$raw_rc"
  expect_eq  "unreadable file exits 1" 1 "$RC"
  expect_has "unreadable file: the message names the path" "$CH/commands/locked.md" "$ERR"
  expect_eq  "unreadable file: nothing on stdout" "" "$OUT"
else
  printf 'skip  unreadable file (running as root)\n'
fi

# ---------- static checks ----------
if bash -n "$SS" && bash -n "$TEST_SELF"; then ok "bash -n on both scripts"; else fail "bash -n on both scripts" "syntax error"; fi
if [ -n "$SHELLCHECK" ]; then
  if out=$("$SHELLCHECK" "$SS" "$TEST_SELF" 2>&1); then ok "shellcheck on both scripts"
  else fail "shellcheck on both scripts" "$out"; fi
else
  printf 'skip  shellcheck not installed (CI runs it)\n'
fi

# ---------- nothing written, no network, no model ----------
expect_eq "skill-show wrote nothing under HOME or the project" "$BEFORE" "$(snapshot)"
for t in curl wget claude; do
  if [ -e "$TMP/$t.log" ]; then fail "never calls $t" "$(cat "$TMP/$t.log")"; else ok "never calls $t"; fi
done

# ---------- result ----------
if [ "$fails" -eq 0 ]; then printf '\nall tests passed\n'; else printf '\n%s test(s) failed\n' "$fails"; fi
[ "$fails" -eq 0 ]
