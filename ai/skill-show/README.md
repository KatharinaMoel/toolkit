# skill-show — read a skill or slash command yourself, unchanged

Skills and slash commands for Claude Code live in at least ten places: your
own, a project's, generated ones, synced ones from claude.ai, and plugins. To
see what one tells the agent you first have to find the file, and then you
often ask a model to read it — which filters the very text you wanted to see.

`skill-show <name>` finds the file Claude Code uses for `/<name>` and prints it
**byte for byte**, with its path in front. No model is involved, nothing is
written, nothing goes over the network.

```
$ skill-show /open-topics
==> /open-topics · command · personal · active
    file:    /home/me/.claude/commands/open-topics.md
    source:  /home/me/notes/40-runbooks/open-topics.md (kios sync: edit the source, not this file)
    > cat '/home/me/.claude/commands/open-topics.md'
──── begin ────
…the file, unchanged…
──── end of /home/me/.claude/commands/open-topics.md ────
```

## Inside Claude Code

```
! skill-show feature-bauen
! skill-show /superpowers:brainstorming
! skill-show                       # the list of every name
! skill-show code-review --path    # only the path
```

The `!` prefix runs the command in a shell and puts its output into the chat
unchanged. There is no terminal behind `!`, so skill-show never opens the
picker there. Observed with Claude Code 2.1.302 on 2026-10-18 (not documented):
`!` shows stderr in the chat too, merged into the same block, so the notes
skill-show prints on stderr are visible.

## Usage

```bash
skill-show <name>            # the active file, then the shadowed ones as one line each
skill-show <name> --all      # the content of every match, in precedence order
skill-show <name> --path     # only the active path (with --all: every match)
skill-show <name> --raw      # only the content of the active match (for diff and pipes)
skill-show <name> --pretty   # content through bat: colour only, text unchanged
skill-show                   # list; in a terminal with fzf a picker (enter shows, esc quits)
skill-show --list            # always the plain list
skill-show --tsv             # one entry per line, 8 tab-separated columns
skill-show --project <dir>   # take <dir> as the project
```

`<name>` works with or without a leading slash, and as `plugin:skill`. Only ASCII
letters, digits, `.`, `_` and `-` are allowed in each part, so a name can never
become a path outside the search folders.

- The block between `──── begin ────` and the end line is the file's bytes. A
  file without a final newline gets one newline before the end line, and the end
  line says `(no newline at end of file)`.
- `link:` shows the real path when the file lies behind a symlink; `more:` lists
  the other files of a skill folder (up to 50), without their content.
- `--pretty` runs `bat --language=markdown --style=plain --paging=never --tabs=0
  --wrap=never`: without the last two, bat turns tabs into spaces and wraps long
  lines on a terminal. Without bat it says so and prints plain text.
- `--raw` with a name that has several matches it cannot rank prints the first
  one and says so on stderr.

Exit codes: 0 printed · 1 not found or unreadable · 2 usage error, invalid name,
or `plugin:skill` without `jq` · 130 picker closed with esc.

## Where it looks

| # | Group | Path | Invoked as |
|---|---|---|---|
| 1 | managed | `/etc/claude-code/.claude/skills/<dir>/SKILL.md` | `/<name>` |
| 2 | personal skill | `~/.claude/skills/<dir>/SKILL.md` (a symlinked folder is fine) | `/<name>` |
| 3 | project skill | `<project>/.claude/skills/<dir>/SKILL.md` | `/<name>` |
| 4 | nested skill | `.claude/skills` in each folder from here up to, not including, the project root | `/<name>` |
| 5 | extra dir skill | `.claude/skills` in each `EXTRA_DIRS` folder (stands in for `--add-dir`) | `/<name>` |
| 6 | personal command | `~/.claude/commands/<name>.md`; `<sub>/<name>.md` | `/<name>`; `/<sub>:<name>` |
| 7 | project command | `<project>/.claude/commands/<name>.md`; `<sub>/<name>.md` | `/<name>`; `/<sub>:<name>` |
| 8 | claude.ai skill | `~/.claude/skills/synced/<bucket>/<dir>/SKILL.md`, folders named in its `manifest.json` | `/anthropic-skills:<name>` |
| 9 | plugin | `skills/<dir>/SKILL.md` and `commands/<name>.md` under the `installPath` in `~/.claude/plugins/installed_plugins.json` | `/<plugin>:<name>` |
| 10 | claude.ai plugin | `~/.claude/plugins/synced/<bucket>/<plugin>~g<generation>/…` | `/<plugin>:<name>` |

- `~/.claude` is `$CLAUDE_CONFIG_DIR` when that is set. The project is the git
  repository around the current folder, else the current folder.
- A skill is found by its `name:` and by its folder name (the docs: "The
  directory name also invokes the skill"); the list shows `/beta [renamed]`.
- Entries starting with `.` are skipped (`~/.claude/skills/.trash/` holds deleted
  skills). Missing folders are normal and produce no message.
- The plugin prefix is `name` in `.claude-plugin/plugin.json`, not the folder
  (`pydantic-ai` is `/ai:…`); without one, the install key before `@`.
- Plugins count **only** at their `installPath`: the cache keeps old versions and
  temporary clones. A plugin set to `false` in `enabledPlugins` is still shown,
  labelled `(disabled)`; per plugin, `.claude/settings.local.json` beats
  `.claude/settings.json` beats `~/.claude/settings.json`. An install with a scope
  other than `user` is labelled `(scope: …, project unknown)`: no project path
  field is documented.
- **Groups 8 and 10 are best-effort.** Their layout (`synced/`, `manifest.json`,
  `~g<N>`, `.in_use`, the prefix `anthropic-skills`) was observed on 2026-10-18,
  not documented. Without a usable manifest, a claude.ai plugin counts in the
  folder marked `.in_use`. `SYNCED_SKILL_PREFIX` overrides the prefix.
- Without `jq`, groups 8–10 are skipped with a note; local skills and commands
  keep working, and `plugin:skill` exits 2.
- **Bundled skills** (`/simplify`, `/loop`, …) are compiled into the Claude Code
  program. There is no file to show and no official way to print their text, so
  skill-show says so, and lists prefixed names with the same name instead
  (`/code-review` runs the bundled skill, never `/engineering:code-review`).

## Precedence

A bare name looks in groups 1–7. The first match in this order is `active`:

1. managed skill
2. personal skill
3. project skill
4. nested skills, nearest folder first
5. extra dir skills
6. personal command
7. project command

The others are `shadowed`, except a nested skill next to a project skill of the
same name: the docs say both stay available, so it is `also loaded`.

Documented (code.claude.com/docs/en/skills, read 2026-10-18): managed > personal >
project; a skill beats a command file of the same name; nested and project skills
both load. **Not documented: a command on a higher level against a skill on a
lower level** (personal command vs. project skill). skill-show puts all skills
before all commands — "the skill wins" is the only documented rule between the
kinds — and marks that one case in the header as `active (by the precedence in
the README)`. It was not live-tested.

A prefixed name looks in groups 8–10 and in command subfolders. When two matches
share it (two marketplaces with the same plugin name, or a plugin and a command
subfolder), skill-show shows both and says it cannot tell which one Claude Code
uses. Names are matched case-sensitively; the docs say nothing general about case.

## kios-generated files

Files written by `kios sync` carry a marker
`<!-- kios:generated | Quelle: <path> | … -->`, on line 1, 4 or 5. As kios
itself does, skill-show searches the first 2000 bytes. The header shows the
source as a full path when one of `SOURCE_ROOTS` has it, else the raw value with
the reason. skill-show only checks that the source exists; it never reads or
prints it.

## List and TSV

The list groups entries by place, sorted by name, with the folder when it
differs from `name:`, the target of a symlinked skill, the raw kios source, and
`(shadowed by …)` or `(also loaded)`.

`--tsv` columns, stable for scripts (recall, phase 2):

```
invocation  kind  group  name  file  status  kios-source  description
```

`kind` is `skill` or `command`; `group` is the id (`managed`, `personal-skill`,
`project-skill`, `nested`, `extra`, `personal-command`, `project-command`,
`claude-ai-skill`, `plugin`, `claude-ai-plugin`); `status` is `active`,
`shadowed`, `also-loaded` or `disabled`. A tab inside a value becomes a space, in
this output only. Two plugins with the same prefixed name are both `active` here.

Front matter values with the control byte `\037`, CR or tab are shown with spaces,
and files whose name contains a newline are skipped with a note, so no file can
make skill-show print another file under its name.

## Requirements

- Bash 5, coreutils, `awk`, `sed`, `find`, `git`
- `jq` for plugins and claude.ai skills
- Optional: `fzf` (picker), `bat` (`--pretty`)

Fedora: `sudo dnf install jq fzf bat`

## Setup

```bash
ln -s "$PWD/ai/skill-show/skill-show" ~/.local/bin/skill-show
mkdir -p ~/.config/skill-show
cp ai/skill-show/example.conf ~/.config/skill-show/skill-show.conf   # optional, then edit
```

Every setting is optional: `SOURCE_ROOTS`, `EXTRA_DIRS`, `BUILTIN_NAMES`,
`SYNCED_SKILL_PREFIX` (see `example.conf`).

## Tests

```bash
bash ai/skill-show/test_skill_show.sh
```

Runs in a throwaway `HOME` and project with stubs for `fzf`, `bat`, `curl`,
`wget` and `claude`; it checks that the stubs for network and model are never
called and that no file under `HOME` or the project changes. Two variables exist
for the tests only: `SKILL_SHOW_MANAGED_DIR` (instead of `/etc/claude-code`) and
`SKILL_SHOW_FORCE_TTY=1` (act as if on a terminal, to test the picker).

The design is `docs/superpowers/specs/2026-10-18-skill-show-design.md`.
