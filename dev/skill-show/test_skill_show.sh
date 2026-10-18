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
         grep head tail tr wc find git od cmp sha256sum mkdir ln chmod id ls seq paste cp; do
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
# bat also prints the file it was given last, like the real one does without colour.
# shellcheck disable=SC2016  # unexpanded on purpose: it is the stub's code
printf 'for last; do :; done\ncat -- "$last"\n' >> "$STUBS/bat"
# fzf also keeps its input in $TMP/fzf.in; with $FZF_PICK set it picks the first
# line containing it, otherwise it quits like esc (exit 130).
cat >> "$STUBS/fzf" <<'EOF'
cat > "$FZF_IN"
[ -n "${FZF_PICK:-}" ] || exit 130
grep -m1 -F -- "$FZF_PICK" "$FZF_IN" || exit 1
EOF
export FZF_IN="$TMP/fzf.in"
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
put "$TMP/proj/.claude/skills/alpha/SKILL.md"    '---\nname: alpha\n---\nproject alpha\n'
put "$TMP/proj/.claude/skills/crossy/SKILL.md"   '---\nname: crossy\n---\nproject skill crossy\n'
put "$CH/commands/crossy.md"                     'personal command crossy\n'
put "$TMP/proj/pkg/.claude/skills/nest/SKILL.md"     '---\nname: nest\n---\nnested skill\n'
put "$TMP/proj/pkg/.claude/skills/projonly/SKILL.md" '---\nname: projonly\n---\nnested projonly\n'
put "$CH/commands/sub/nested-cmd.md"             'command in a subfolder\n'
put "$SKILL_SHOW_MANAGED_DIR/.claude/skills/mgd/SKILL.md" '---\nname: mgd\n---\nmanaged skill\n'
put "$TMP/extra/.claude/skills/xtra/SKILL.md"    '---\nname: xtra\n---\nextra dir skill\n'
# Front matter and file names that try to break the \037/newline records:
# a name: with \037 would shift the file field to $TMP/secret.txt.
printf 'TOPSECRET\n' > "$TMP/secret.txt"
printf -- '---\nname: evil\0371\0372\0373\0374\037%s\ndescription: d\037e\r\n---\ninject body\n' "$TMP/secret.txt" \
  > "$(mkdir -p "$CH/skills/inject" && printf '%s' "$CH/skills/inject/SKILL.md")"
put "$CH/commands/nl"$'\n'"fake.md" 'newline in the file name\n'
# kios-generated commands: the marker on line 4, 5 or 1 (before the front matter)
# shellcheck disable=SC2016  # the backticks are part of the kios marker text
marker() { printf '<!-- kios:generated | Quelle: %s | Nicht von Hand aendern - aendere die Quelle und fuehre `kios sync` aus. -->' "$1"; }
printf -- '---\ndescription: four\n---\n%s\nbody four\n' "$(marker 40-runbooks/x.md)" > "$CH/commands/gen4.md"
printf -- '---\ndescription: five\nargument-hint: x\n---\n%s\nbody five\n' "$(marker 40-runbooks/x.md)" > "$CH/commands/gen5.md"
printf -- '%s\n---\ndescription: one\n---\nbody one\n' "$(marker templates/merken.md)" > "$TMP/proj/.claude/commands/gen1.md"
# a marker after the first 2000 bytes does not count
{ printf 'filler %.0s' $(seq 1 300); printf '\n%s\n' "$(marker 40-runbooks/x.md)"; } > "$CH/commands/late.md"
put "$TMP/Mein Vault/40-runbooks/x.md" 'VAULT-SECRET\n'   # space on purpose; must never be printed
# installed plugins: only installPath counts, never the rest of the cache
PC="$CH/plugins/cache"
plugin() { # plugin <root> <plugin.json name or ""> : a plugin folder with its manifest
  if [ -n "$2" ]; then put "$1/.claude-plugin/plugin.json" "{\"name\": \"$2\", \"version\": \"x\"}\n"
  else put "$1/.claude-plugin/plugin.json" '{"description": "no name"}\n'; fi
}
plugin "$PC/mkt/superpowers/7.0.0" superpowers
put "$PC/mkt/superpowers/7.0.0/skills/brainstorming/SKILL.md" '---\nname: brainstorming\n---\nNEW brainstorming\n'
put "$PC/mkt/superpowers/7.0.0/commands/sp-cmd.md" 'plugin command\n'
plugin "$PC/mkt/superpowers/6.4.1" superpowers
put "$PC/mkt/superpowers/6.4.1/skills/brainstorming/SKILL.md" '---\nname: brainstorming\n---\nOLD brainstorming\n'
put "$PC/temp_subdir_1_x.clone/plugins/superpowers/skills/brainstorming/SKILL.md" '---\nname: brainstorming\n---\nTEMP brainstorming\n'
plugin "$PC/mkt/pydantic-ai/0.1.0" ai
put "$PC/mkt/pydantic-ai/0.1.0/skills/building-pydantic-ai-agents/SKILL.md" '---\nname: building-pydantic-ai-agents\n---\npydantic body\n'
put "$PC/mkt/pydantic-ai/0.1.0/skills/collide/SKILL.md" '---\nname: collide\n---\nplugin collide\n'
put "$CH/commands/ai/collide.md" 'subfolder collide\n'
plugin "$PC/mkt/offplug/1.0.0" offplug
put "$PC/mkt/offplug/1.0.0/skills/offskill/SKILL.md" '---\nname: offskill\n---\noff body\n'
plugin "$PC/mkt/localon/1.0.0" localon
put "$PC/mkt/localon/1.0.0/skills/onskill/SKILL.md" '---\nname: onskill\n---\non body\n'
plugin "$PC/mkt/projplug/1.0.0" projplug
put "$PC/mkt/projplug/1.0.0/skills/pskill/SKILL.md" '---\nname: pskill\n---\nproject scope body\n'
plugin "$PC/mkt/twin/1.0.0" twin
put "$PC/mkt/twin/1.0.0/skills/same/SKILL.md" '---\nname: same\n---\nTWIN ONE\n'
plugin "$PC/other/twin/2.0.0" twin
put "$PC/other/twin/2.0.0/skills/same/SKILL.md" '---\nname: same\n---\nTWIN TWO\n'
plugin "$PC/mkt/nameless/1.0.0" ""
put "$PC/mkt/nameless/1.0.0/skills/nskill/SKILL.md" '---\nname: nskill\n---\nnameless body\n'
inst() { printf '"%s": [{"scope": "%s", "installPath": "%s", "version": "%s"}]' "$1" "$2" "$3" "$4"; }
{ printf '{"version": 2, "plugins": {'
  inst superpowers@mkt user "$PC/mkt/superpowers/7.0.0" 7.0.0; printf ', '
  inst pydantic-ai@mkt user "$PC/mkt/pydantic-ai/0.1.0" 0.1.0; printf ', '
  inst offplug@mkt user "$PC/mkt/offplug/1.0.0" 1.0.0; printf ', '
  inst localon@mkt user "$PC/mkt/localon/1.0.0" 1.0.0; printf ', '
  inst projplug@mkt project "$PC/mkt/projplug/1.0.0" 1.0.0; printf ', '
  inst twin@mkt user "$PC/mkt/twin/1.0.0" 1.0.0; printf ', '
  inst twin@other user "$PC/other/twin/2.0.0" 2.0.0; printf ', '
  inst nameless@mkt user "$PC/mkt/nameless/1.0.0" 1.0.0
  printf '}}\n'; } > "$CH/plugins/installed_plugins.json"
put "$CH/settings.json" '{"enabledPlugins": {"offplug@mkt": false, "localon@mkt": false, "superpowers@mkt": true}}\n'
put "$TMP/proj/.claude/settings.local.json" '{"enabledPlugins": {"localon@mkt": true}}\n'
# claude.ai skills (observed layout)
SS_SYNC="$CH/skills/synced/bucket1"
put "$SS_SYNC/manifest.json" '{"skills": [{"name": "pdf", "skillId": "pdf"}, {"name": "../escape"}]}\n'
put "$SS_SYNC/pdf/SKILL.md" '---\nname: pdf\n---\nsynced pdf\n'
put "$SS_SYNC/notlisted/SKILL.md" '---\nname: notlisted\n---\nnot in the manifest\n'
put "$SS_SYNC/.bucket-x" '\n'
put "$CH/skills/synced/escape/SKILL.md" '---\nname: escape\n---\nreached through ../escape\n'
# claude.ai plugins: the manifest names generation 3; the old folder sits next to it
PS_SYNC="$CH/plugins/synced/bucket2"
put "$PS_SYNC/manifest.json" '{"plugins": [{"name": "engineering", "generation": 3}]}\n'
plugin "$PS_SYNC/engineering" engineering
put "$PS_SYNC/engineering/skills/code-review/SKILL.md" '---\nname: code-review\n---\nOLD engineering\n'
plugin "$PS_SYNC/engineering~g3" engineering
put "$PS_SYNC/engineering~g3/skills/code-review/SKILL.md" '---\nname: code-review\n---\nNEW engineering\n'
: > "$PS_SYNC/engineering~g3/.in_use"

CONF="$HOME/.config/skill-show/skill-show.conf"
: > "$CONF"   # exists from the start, so tests can fill and empty it without changing the snapshot

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

# ---------- precedence and shadowed matches ----------
in_dir() { # in_dir <dir> <args...>: run skill-show from <dir>; sets RC, OUT, ERR
  (cd "$1" && shift && "$SS" "$@" > "$TMP/out" 2> "$TMP/err"); RC=$?
  OUT=$(cat "$TMP/out"); ERR=$(cat "$TMP/err")
}
in_dir "$TMP/proj" alpha
expect_has "alpha in the project: personal skill active" "==> /alpha · skill · personal · active" "$OUT"
expect_has "alpha in the project: project skill shadowed" "    shadowed: /alpha · skill · project · $TMP/proj/.claude/skills/alpha/SKILL.md" "$OUT"
expect_has "alpha in the project: personal command shadowed" "    shadowed: /alpha · command · personal · $CH/commands/alpha.md" "$OUT"
expect_eq  "shadowed lines follow the end line, best first" \
  "/alpha · skill · project|/alpha · command · personal" \
  "$(sed -n '/^──── end of /,$p' "$TMP/out" | grep '^    shadowed: ' | cut -d' ' -f6-10 | paste -sd'|')"
expect_eq  "only the active file's content is shown" 1 "$(grep -c '^──── begin ────$' "$TMP/out")"

in_dir "$TMP/proj" alpha --all
expect_eq  "--all shows every match" 3 "$(grep -c '^──── begin ────$' "$TMP/out")"
expect_has "--all: the shadowed block says so" "==> /alpha · skill · project · shadowed by personal skill" "$OUT"
in_dir "$TMP/proj" alpha --path --all
expect_eq  "--path --all: one path per match, in precedence order" \
  "$CH/skills/alpha/SKILL.md|$TMP/proj/.claude/skills/alpha/SKILL.md|$CH/commands/alpha.md" "$(paste -sd'|' "$TMP/out")"
in_dir "$TMP/proj" alpha --path
expect_eq  "--path alone: only the active path" "$CH/skills/alpha/SKILL.md" "$OUT"
run alpha --project "$TMP/proj"
expect_has "--project from outside sees the project skill" "    shadowed: /alpha · skill · project" "$OUT"

in_dir "$TMP/proj/pkg" projonly
expect_has "projonly from pkg: project skill active" "==> /projonly · skill · project · active" "$OUT"
expect_has "projonly from pkg: nested skill also loaded" "    also loaded: /projonly · skill · nested · $TMP/proj/pkg/.claude/skills/projonly/SKILL.md" "$OUT"
in_dir "$TMP/proj/pkg" nest
expect_has "nested skill found from its folder" "==> /nest · skill · nested · active" "$OUT"
in_dir "$TMP/proj" nest
expect_eq  "nested skill not found from the project root" 1 "$RC"
run nest --project "$TMP/proj"
expect_eq  "no nested search from outside the project" 1 "$RC"

in_dir "$TMP/proj" crossy
expect_has "personal command vs. project skill: marked as unverified" \
  "==> /crossy · skill · project · active (by the precedence in the README)" "$OUT"
expect_has "personal command vs. project skill: command shadowed" "    shadowed: /crossy · command · personal" "$OUT"

run mgd
expect_has "managed skill found" "==> /mgd · skill · managed · active" "$OUT"

run xtra
expect_eq  "extra dir skill needs EXTRA_DIRS" 1 "$RC"
printf 'EXTRA_DIRS=("%s")\n' "$TMP/extra" > "$CONF"
run xtra
: > "$CONF"
expect_has "extra dir skill found with EXTRA_DIRS" "==> /xtra · skill · extra dir · active" "$OUT"

run sub:nested-cmd
expect_has "command in a subfolder runs as /sub:name" "==> /sub:nested-cmd · command · personal · active" "$OUT"
run /sub:nested-cmd --path
expect_eq  "/sub:name with slash, --path" "$CH/commands/sub/nested-cmd.md" "$OUT"
run nested-cmd
expect_eq  "a subfolder command is not found by its bare name" 1 "$RC"

# ---------- kios source ----------
printf 'SOURCE_ROOTS=("%s")\n' "$TMP/Mein Vault" > "$CONF"
run gen4
expect_has "marker on line 4: source resolved to a full path" \
  "    source:  $TMP/Mein Vault/40-runbooks/x.md (kios sync: edit the source, not this file)" "$OUT"
run gen5
expect_has "marker on line 5: source resolved" "    source:  $TMP/Mein Vault/40-runbooks/x.md (kios sync" "$OUT"
expect_eq  "source: comes after file: and before the cat line" "file:|source:|>" \
  "$(sed -n '2,4p' "$TMP/out" | awk '{print $1}' | paste -sd'|')"
run gen1 --project "$TMP/proj"
expect_has "marker on line 1: found; unresolvable source printed raw" \
  "    source:  templates/merken.md (kios; not found under SOURCE_ROOTS)" "$OUT"
for n in gen4 gen5 gen1; do
  run "$n" --project "$TMP/proj"
  expect_not "$n: the source note itself is never printed" "VAULT-SECRET" "$OUT$ERR"
done
run late
expect_not "a marker after 2000 bytes does not count" "source:" "$OUT"
run plain
expect_not "a plain command has no source:" "source:" "$OUT"
: > "$CONF"
run gen4
expect_has "without SOURCE_ROOTS: raw value and the hint to set it" \
  "    source:  40-runbooks/x.md (kios; set SOURCE_ROOTS in ~/.config/skill-show/skill-show.conf to resolve it)" "$OUT"

# ---------- plugins ----------
run superpowers:brainstorming
expect_eq  "plugin skill: exit 0" 0 "$RC"
expect_has "plugin skill: header names plugin, version, marketplace" \
  "==> /superpowers:brainstorming · skill · plugin superpowers 7.0.0 (mkt) · active" "$OUT"
expect_has "plugin skill: the installed version's file" "NEW brainstorming" "$OUT"
expect_not "plugin skill: never an old cached version" "OLD brainstorming" "$OUT"
expect_not "plugin skill: never a temporary clone" "TEMP brainstorming" "$OUT"
run /superpowers:brainstorming --path
expect_eq  "/plugin:skill --path" "$PC/mkt/superpowers/7.0.0/skills/brainstorming/SKILL.md" "$OUT"
run superpowers:sp-cmd
expect_has "plugin command" "==> /superpowers:sp-cmd · command · plugin superpowers 7.0.0 (mkt) · active" "$OUT"
run ai:building-pydantic-ai-agents
expect_has "prefix is the plugin.json name" "pydantic body" "$OUT"
run pydantic-ai:building-pydantic-ai-agents
expect_eq  "the folder name is not the prefix" 1 "$RC"
run nameless:nskill
expect_has "plugin.json without a name: the install key is the prefix" "nameless body" "$OUT"
run offplug:offskill
expect_has "disabled plugin: still shown, labelled" "plugin offplug 1.0.0 (mkt) (disabled) · active" "$OUT"
run localon:onskill
expect_has "disabled in user settings" "(disabled)" "$OUT"
in_dir "$TMP/proj" localon:onskill
expect_not "settings.local.json of the project enables it again" "(disabled)" "$OUT"
run projplug:pskill
expect_has "project scope without a known project path: labelled" "(scope: project, project unknown)" "$OUT"
run twin:same
expect_eq  "same plugin name from two marketplaces: exit 0" 0 "$RC"
expect_eq  "same plugin name from two marketplaces: both shown" 2 "$(grep -c '^──── begin ────$' "$TMP/out")"
expect_has "same plugin name from two marketplaces: says it cannot tell" "cannot tell which one Claude Code uses" "$OUT"
run twin:same --raw
expect_has "ambiguous with --raw: says on stderr which match it printed" "cannot tell which one Claude Code uses" "$ERR"
run ai:collide
expect_eq  "subfolder command and plugin skill with one prefix: both shown" 2 "$(grep -c '^──── begin ────$' "$TMP/out")"
expect_has "subfolder command and plugin skill: says it cannot tell" "cannot tell which one Claude Code uses" "$OUT"
run brainstorming
expect_eq  "a bare name never falls through to a plugin" 1 "$RC"
expect_eq  "a bare name never falls through to a plugin: stdout empty" "" "$OUT"

# ---------- claude.ai skills and plugins ----------
run anthropic-skills:pdf
expect_has "claude.ai skill" "==> /anthropic-skills:pdf · skill · claude.ai skill · active" "$OUT"
expect_has "claude.ai skill: its file" "synced pdf" "$OUT"
run anthropic-skills:notlisted
expect_eq  "claude.ai skill not in the manifest: not found" 1 "$RC"
run anthropic-skills:escape
expect_eq  "a manifest name with a path never leaves the bucket" 1 "$RC"
run engineering:code-review
expect_has "claude.ai plugin: header names the generation" \
  "==> /engineering:code-review · skill · claude.ai plugin engineering (generation 3) · active" "$OUT"
expect_has "claude.ai plugin: the generation the manifest names" "NEW engineering" "$OUT"
cp "$PS_SYNC/manifest.json" "$TMP/manifest.bak"; : > "$PS_SYNC/manifest.json"
run engineering:code-review
expect_has "claude.ai plugin without a readable manifest: the .in_use folder" "NEW engineering" "$OUT"
printf 'not json' > "$PS_SYNC/manifest.json"; "$RM" "$PS_SYNC/engineering~g3/.in_use"
run engineering:code-review
expect_eq  "claude.ai plugin with neither: not found" 1 "$RC"
expect_has "claude.ai plugin with neither: a note on stderr" ".in_use" "$ERR"
: > "$PS_SYNC/engineering~g3/.in_use"; cat "$TMP/manifest.bak" > "$PS_SYNC/manifest.json"

# ---------- without jq, and with a broken installed_plugins.json ----------
PATH="$STUBS:$SYS" "$SS" alpha > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "no jq: a personal skill still works" 0 "$RC"
PATH="$STUBS:$SYS" "$SS" superpowers:brainstorming > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "no jq: plugin:skill exits 2" 2 "$RC"
expect_has "no jq: the message names the install command" "sudo dnf install jq" "$(cat "$TMP/err")"
PATH="$STUBS:$SYS" "$SS" sub:nested-cmd > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "no jq: a subfolder command still shows" 0 "$RC"
expect_has "no jq: and says plugins were not checked" "jq is missing" "$(cat "$TMP/err")"
cp "$CH/plugins/installed_plugins.json" "$TMP/inst.bak"; printf '{broken' > "$CH/plugins/installed_plugins.json"
run superpowers:brainstorming
expect_eq  "broken installed_plugins.json: plugin not found" 1 "$RC"
expect_has "broken installed_plugins.json: a note names the file" "installed_plugins.json" "$ERR"
run engineering:code-review
expect_eq  "broken installed_plugins.json: claude.ai plugins still work" 0 "$RC"
run alpha
expect_eq  "broken installed_plugins.json: personal skills still work" 0 "$RC"
cat "$TMP/inst.bak" > "$CH/plugins/installed_plugins.json"

# ---------- not found ----------
run brainstorming
expect_eq  "not found: exit 1" 1 "$RC"
expect_eq  "not found: nothing on stdout" "" "$OUT"
expect_has "not found: says so" "skill-show: no file for /brainstorming." "$ERR"
expect_has "not found: points to the places in --help" "skill-show --help lists them" "$ERR"
expect_has "not found: suggests the plugin skill" "Plugin skills with this name: /superpowers:brainstorming" "$ERR"
run code-review
expect_has "not found: suggests the claude.ai plugin skill" "Plugin skills with this name: /engineering:code-review" "$ERR"
run sp-cmd
expect_has "not found: suggests the plugin command" "Plugin commands with this name: /superpowers:sp-cmd" "$ERR"
run nested-cmd
expect_has "not found: suggests the subfolder command" "Commands in a subfolder with this name: /sub:nested-cmd" "$ERR"
run simplify
expect_has "unknown name: most likely bundled" "most likely a bundled skill or a built-in command" "$ERR"
expect_not "unknown name: no suggestion line" "with this name" "$ERR"
printf 'BUILTIN_NAMES=(loop simplify)\n' > "$CONF"
run /simplify
: > "$CONF"
expect_has "name in BUILTIN_NAMES: said plainly" "/simplify is a bundled skill or built-in command of Claude Code" "$ERR"
expect_not "name in BUILTIN_NAMES: no 'most likely'" "most likely" "$ERR"
run pydantic-ai:building-pydantic-ai-agents
expect_has "prefixed not found: explains the prefix" "the name in its plugin.json" "$ERR"
run --help
expect_has "--help lists where it looks" "/etc/claude-code/.claude/skills" "$OUT"
expect_has "--help lists the plugin places" "installed_plugins.json" "$OUT"

# ---------- list ----------
run
expect_eq  "list: exit 0" 0 "$RC"
LIST=$OUT
expect_has "list: group heading with its folder" "personal skills  $CH/skills" "$LIST"
expect_has "list: a skill whose folder differs shows the folder" "  /beta [renamed]" "$LIST"
expect_has "list: a symlinked skill shows where it points" "-> $TMP/outside/link skill" "$LIST"
expect_has "list: kios source, raw" "kios: 40-runbooks/x.md" "$LIST"
expect_has "list: shadowed entries say so" "(shadowed by personal skill)" "$LIST"
expect_has "list: plugin heading" "plugin superpowers 7.0.0 (mkt)  $PC/mkt/superpowers/7.0.0" "$LIST"
expect_has "list: disabled plugin heading" "plugin offplug 1.0.0 (mkt) (disabled)" "$LIST"
expect_has "list: claude.ai plugin heading" "claude.ai plugin engineering (generation 3)" "$LIST"
expect_eq  "list: last line names what has no file" \
  "not files: bundled skills and built-in commands of Claude Code (see skill-show --help)" "$(tail -n1 "$TMP/out")"
for inv in /plain /superpowers:brainstorming /engineering:code-review /anthropic-skills:pdf /sub:nested-cmd /mgd /gen4; do
  expect_eq "list: $inv exactly once" 1 "$(grep -c -- "^  $inv\( \|$\)" "$TMP/out")"
done
expect_eq  "list: /alpha twice (skill and command)" 2 "$(grep -c -- '^  /alpha\( \|$\)' "$TMP/out")"
for gone in /old /anthropic-skills:notlisted /anthropic-skills:escape .bucket; do
  expect_not "list: never $gone" "$gone" "$LIST"
done
expect_not "list: never an old plugin version" "6.4.1" "$LIST"
expect_not "list: never a temporary clone" "temp_subdir" "$LIST"
in_dir "$TMP/proj/pkg" --list
expect_has "list from pkg: nested skill also loaded" "(also loaded)" "$OUT"
expect_has "list from pkg: nested heading with its folder" "nested skills  $TMP/proj/pkg/.claude/skills" "$OUT"

# ---------- --tsv ----------
run --tsv
TSV=$OUT
expect_eq  "--tsv: exit 0" 0 "$RC"
expect_eq  "--tsv: every line has 8 fields" "" "$(awk -F'\t' 'NF != 8' "$TMP/out")"
expect_eq  "--tsv: status is one of four values" "" "$(cut -f6 "$TMP/out" | grep -vxE 'active|shadowed|also-loaded|disabled')"
expect_has "--tsv: a shadowed command" "$(printf '/alpha\tcommand\tpersonal-command\talpha\t%s\tshadowed' "$CH/commands/alpha.md")" "$TSV"
expect_has "--tsv: kios source and description" "$(printf '\tactive\t40-runbooks/x.md\tfour')" "$TSV"
expect_has "--tsv: disabled plugin" "$(printf '/offplug:offskill\tskill\tplugin\toffskill\t%s\tdisabled' "$PC/mkt/offplug/1.0.0/skills/offskill/SKILL.md")" "$TSV"
expect_not "--tsv: no heading lines" "not files" "$TSV"
in_dir "$TMP/proj/pkg" --tsv
expect_has "--tsv from pkg: also-loaded" "$(printf '\tnested\tprojonly\t%s\talso-loaded' "$TMP/proj/pkg/.claude/skills/projonly/SKILL.md")" "$OUT"

# ---------- picker ----------
"$RM" -f "$TMP/fzf.log"
run
expect_eq  "no terminal: fzf is never called" "no" "$([ -e "$TMP/fzf.log" ] && echo yes || echo no)"
SKILL_SHOW_FORCE_TTY=1 FZF_PICK=/plain "$SS" > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "picker: enter shows the picked entry" "$("$SS" plain 2>/dev/null)" "$(cat "$TMP/out")"
expect_eq  "picker: exit 0" 0 "$RC"
expect_has "picker: fzf gets the entries" "/superpowers:brainstorming" "$(cat "$FZF_IN")"
expect_has "picker: the preview is skill-show --raw" "--raw {1}" "$(cat "$TMP/fzf.log")"
SKILL_SHOW_FORCE_TTY=1 "$SS" > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "picker: esc exits 130" 130 "$RC"
expect_eq  "picker: esc prints nothing" "" "$(cat "$TMP/out")"
"$RM" -f "$TMP/fzf.log"
SKILL_SHOW_FORCE_TTY=1 "$SS" --list > "$TMP/out" 2>&1
expect_eq  "--list: never the picker" "no" "$([ -e "$TMP/fzf.log" ] && echo yes || echo no)"
PATH="$JQBIN:$SYS" SKILL_SHOW_FORCE_TTY=1 "$SS" > "$TMP/out" 2>&1; RC=$?
expect_eq  "terminal without fzf: the plain list" 0 "$RC"
expect_has "terminal without fzf: the plain list" "personal skills" "$(cat "$TMP/out")"

# ---------- final review fixes ----------
# A Claude home without any synced folder: no note about folders that do not exist.
mkdir -p "$TMP/bare/skills/only"; printf -- '---\nname: only\n---\nx\n' > "$TMP/bare/skills/only/SKILL.md"
CLAUDE_CONFIG_DIR="$TMP/bare" "$SS" --list > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "no synced folders: list exit 0" 0 "$RC"
expect_eq  "no synced folders: no note at all" "" "$(cat "$TMP/err")"
CLAUDE_CONFIG_DIR="$TMP/bare" "$SS" x:y > /dev/null 2> "$TMP/err"
expect_not "no synced folders: a prefixed lookup notes nothing about synced/*" "synced" "$(cat "$TMP/err")"

# One unreadable SKILL.md must not wipe the names of the others.
if [ "$(id -u)" -ne 0 ]; then
  put "$CH/skills/aaa0/SKILL.md" '---\nname: aaa0\n---\nlocked\n'
  chmod 000 "$CH/skills/aaa0/SKILL.md"
  run beta
  expect_has "unreadable sibling: beta (name:) still found" "    file:    $CH/skills/renamed/SKILL.md" "$OUT"
  expect_has "unreadable sibling: named in a note" "$CH/skills/aaa0/SKILL.md" "$ERR"
  run --list
  expect_has "unreadable sibling: the list keeps name: values" "  /beta [renamed]" "$OUT"
  chmod 644 "$CH/skills/aaa0/SKILL.md"; "$RM" -r "$CH/skills/aaa0"
fi

# One broken plugin.json must not rename the plugins after it.
SPJ="$PC/mkt/superpowers/7.0.0/.claude-plugin/plugin.json"
cp "$SPJ" "$TMP/spj.bak"; printf '{broken' > "$SPJ"
run ai:building-pydantic-ai-agents
expect_eq  "broken plugin.json elsewhere: ai: still found" 0 "$RC"
expect_has "broken plugin.json: named in a note" "$SPJ" "$ERR"
run superpowers:brainstorming
expect_eq  "broken plugin.json: falls back to the install key, visibly" 0 "$RC"
printf '{"name": "bad name"}' > "$SPJ"
run superpowers:brainstorming
expect_has "plugin.json with an unusable name: named in a note" "$SPJ" "$ERR"
cat "$TMP/spj.bak" > "$SPJ"

# name: with trailing blanks is trimmed, as YAML does.
put "$CH/skills/tdir/SKILL.md" '---\nname: trail \t\n---\ntrailing blanks\n'
run trail
expect_eq  "name: with trailing blanks: found" 0 "$RC"
run --tsv
expect_has "name: with trailing blanks: no blank in the invocation" "$(printf '/trail\tskill')" "$OUT"
"$RM" -r "$CH/skills/tdir"

# installed_plugins.json values cannot shift the record fields either.
cp "$CH/plugins/installed_plugins.json" "$TMP/inst.bak"
sed -i 's/"version": "7.0.0"/"version": "7\\u001fX\\u001fY"/' "$CH/plugins/installed_plugins.json"
run superpowers:brainstorming
expect_has "\\037 in installed_plugins.json: cleaned, no false label" \
  "==> /superpowers:brainstorming · skill · plugin superpowers 7 X Y (mkt) · active" "$OUT"
cat "$TMP/inst.bak" > "$CH/plugins/installed_plugins.json"

# ---------- records cannot be spoofed ----------
for n in 3 4 evil inject fake nl; do
  run "$n"
  expect_not "name '$n': a \\037 in front matter never shows another file" "TOPSECRET" "$OUT"
done
run inject --path
expect_eq  "a \\037 in name: is cleaned, the folder still finds the skill" "$CH/skills/inject/SKILL.md" "$OUT"
run inject
expect_has "a \\037 in name: becomes a space, the whole value stays visible" "==> /evil 1 2 3 4 $TMP/secret.txt · skill · personal · active" "$OUT"
run fake
expect_eq  "a file name with a newline is skipped" 1 "$RC"
run plain
expect_has "a skipped file name is named on stderr, not skipped silently" "skipped a file whose name has a newline" "$ERR"

# ---------- --pretty ----------
: > "$TMP/bat.log"
run plain --pretty
expect_eq  "--pretty: exit 0" 0 "$RC"
expect_eq  "--pretty: bat gets the style options and the file" \
  "--language=markdown|--style=plain|--paging=never|--tabs=0|--wrap=never|--|$CH/commands/plain.md" "$(paste -sd'|' "$TMP/bat.log")"
expect_has "--pretty: header printed by skill-show, not bat" "==> /plain · command · personal · active" "$OUT"
if cmp -s <(after_begin "$TMP/out") <(expected_block "$CH/commands/plain.md"); then ok "--pretty: text unchanged"; else fail "--pretty: text unchanged" "$OUT"; fi
PATH="$JQBIN:$SYS" "$SS" --pretty plain > "$TMP/out" 2> "$TMP/err"; RC=$?
expect_eq  "--pretty without bat: exit 0" 0 "$RC"
expect_has "--pretty without bat: note on stderr" "bat" "$(cat "$TMP/err")"
if cmp -s <(after_begin "$TMP/out") <(expected_block "$CH/commands/plain.md"); then ok "--pretty without bat: plain content"; else fail "--pretty without bat: plain content" "$(cat "$TMP/out")"; fi

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
