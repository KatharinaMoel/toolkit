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
         grep head tail tr wc find git od cmp sha256sum mkdir ln chmod id ls; do
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
