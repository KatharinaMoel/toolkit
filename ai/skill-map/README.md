# skill-map — one page of what your AI agent can use, kept current

Claude Code collects skills, slash commands, agents and hooks from many places:
your own, your projects', plugins, claude.ai. After a few weeks nobody knows any
more what is installed, what is used, and what a skill actually tells the agent.

`skill-map` reads those places (and, for usage counts, the session logs) and builds
a page from them: one lane per place, cheat-sheet tables with usage, a lookup with
search, and the full text of each skill or command one click away — unchanged, or
visibly withheld. A session start hook says when the page is out of date.

It is a sibling of [`ai/skill-show`](../skill-show/), which prints one skill in the
terminal. Both are read-only.

```
skill-map build            # data + page into ~/.local/state/skill-map/build/
xdg-open ~/.local/state/skill-map/build/skill-map.html
```

## Usage

```bash
skill-map build [--out DIR]   # inventory.json, wortlaut.json, index.html, skill-map.html
skill-map diff [--texts]      # what is new, removed or changed since the last publish
skill-map mark-published      # after you published the build: remember it
skill-map check               # session start hook: one line when out of date, else nothing
skill-map fingerprint         # the fingerprint and the set of keys it is computed from
```

- `skill-map.html` holds the data inside and opens from disk in any browser.
- `index.html` + `inventory.json` + `wortlaut.json` are the same page as three files,
  for hosting it, for example as a private claude.ai Artifact.
- `build`, `diff` and `mark-published` name every file they read or write on stderr
  first. `check` stays silent unless it has something to say.

Exit codes: 0 done · 1 runtime error (unreadable or broken required file, named) ·
2 usage or config error. `check` always exits 0.

## Zero config, then your own sources

Without a config file the page shows what Claude Code itself has:

| Lane | Read from |
|---|---|
| Persönliche Commands | `~/.claude/commands/*.md`, `<sub>/<name>.md` as `/<sub>:<name>` |
| Eigene Skills | `~/.claude/skills/*/SKILL.md`, personal agents in `~/.claude/agents/` |
| Installierte Plugins | skills, commands and agents under each `installPath` in `~/.claude/plugins/installed_plugins.json` |
| Von claude.ai synchronisiert | `~/.claude/skills/synced/` and `~/.claude/plugins/synced/` (observed layout, best-effort) |
| Hooks | `type: command` hooks in `~/.claude/settings.json` |
| Verwaltet | `/etc/claude-code/.claude/skills/` |

`~/.claude` is `$CLAUDE_CONFIG_DIR` when set. Everything else is optional and
switched on in `~/.config/skill-map/skill-map.conf` (TOML; every key is explained
in [`example.conf`](example.conf)):

- `vault`: a notes vault with runbooks in `40-runbooks/` (front matter `title`,
  `command`, `status`, `tags`) gets its own lane and a table with status and area.
- `source_roots`: if a tool generates your commands and leaves a marker
  `<!-- kios:generated | Quelle: <path> | … -->` in them, the page links each
  command to its source and marks those whose source is gone.
- `projects`: project folders whose `.claude/` gets a lane (fixed in the config, so
  the page is the same wherever a session starts).
- `tools`, `builtins`, `areas`, `title`, `refresh_hint`, `hide`, `narrative`.

The rules of where things are found and which file wins are skill-show's: name from
`name:` or the folder, skills before commands, personal before project, plugins only
at their `installPath` (never older versions in the cache), the plugin prefix from
`plugin.json`.

## Your narrative

The lists come from the data. What only a person can write — how you work, which
skill you take for what, what stands out — goes into your own file
`~/.config/skill-map/erzaehlung.html` (outside any repository), merged in at build
time. [`example-erzaehlung.html`](example-erzaehlung.html) shows every part:
sections for the slots `ablauf`, `chain`, `wofuer`, `repo-wissen`, `auffaellig`,
notes under lanes, short descriptions for the tables. You refer to entries with
`data-key="KEY"` (`skill-map fingerprint` lists the keys); a reference to something
that no longer exists is struck through on the page and listed at the top.

## What never ends up on the page

- **Texts are shown unchanged or not at all.** A text is withheld, with a German
  reason, when the config says so (`withhold_text`), when the file or its source note
  carries a `classification:` other than `public` or `internal` (or cannot be read),
  when its source note cannot be found, when it is not valid UTF-8, or when it
  contains an account id. Classified files also publish no description, title or
  tags.
- **Session logs** give counts and dates per known entry only. Names that match no
  entry are kept only if they look like a command name (`^/?[A-Za-z0-9._:-]{1,80}$`).
- **Paths** show `~` for your home and `<konto>` for account ids. Plugin author
  e-mail addresses are never copied.
- The page inserts everything from the data as text; only your own narrative is
  inserted as HTML.
- No network, no model: skill-map never calls `claude` or the API.

## Usage counts

From the top-level session logs in `~/.claude/projects/*/*.jsonl` (not subagent
logs): slash commands from `<command-name>` in your messages, skills from `Skill`
calls, agents from `Agent`/`Task` calls. A message copied into a resumed session is
counted once. These are approximations: a slash command that loads a skill can count
twice, and Claude Code deletes old logs after `cleanupPeriodDays`
(default 30 days, per code.claude.com/docs/en/settings-reference, read 2026-10-18).

## Keeping it current

The fingerprint is a hash over the set of entries (key, kind, place, plugin version),
not over usage or texts. `skill-map check` compares it with the one stored by
`mark-published` and prints one line:

- `Skill-Landkarte veraltet (neu: …; entfernt: …; geändert: plugin 1.0→1.1) – <refresh_hint>`
  when entries came, went or a plugin updated;
- `Skill-Landkarte: 2 Texte geändert – <refresh_hint>` when only texts of published
  entries changed;
- nothing when all is equal; `… Prüfung fehlgeschlagen (<reason>)` on any error.

It reads no logs, never reads stdin and always exits 0. Measured on the author's
machine on 2026-10-18: 0.13 s.

As a SessionStart hook in `~/.claude/settings.json` (keep your other hooks; use the
absolute path of your symlink):

```json
"SessionStart": [
  { "matcher": "startup",
    "hooks": [ { "type": "command", "command": "/home/<you>/.local/bin/skill-map check", "timeout": 5 } ] }
]
```

Checked in the hooks docs (code.claude.com/docs/en/hooks, read 2026-10-18):
`startup` is a SessionStart matcher (others: `resume`, `clear`, `compact`, `fork`),
so the reminder comes once per new session. Plain stdout of a SessionStart hook would
go into the model's context; `check` therefore prints JSON with `systemMessage`,
which the docs describe as a message shown to the user (they do not say so for
SessionStart in particular — confirm it once after adding the hook). Which `PATH` a
hook sees is not documented, hence the absolute path.

Publishing is up to you: open `skill-map.html` locally, or put the three files
somewhere. To publish as a claude.ai Artifact, Claude has to do it (the Artifact
tool runs inside a Claude session): build, read `skill-map diff --texts`, publish
`index.html` with `inventory.json` and `wortlaut.json`, then `skill-map
mark-published`.

## Requirements and setup

- Python 3.12 or newer, standard library only; Bash for the launcher.

```bash
ln -s "$PWD/ai/skill-map/skill-map" ~/.local/bin/skill-map
mkdir -p ~/.config/skill-map
cp ai/skill-map/example.conf ~/.config/skill-map/skill-map.conf        # optional
cp ai/skill-map/example-erzaehlung.html ~/.config/skill-map/erzaehlung.html   # optional
skill-map build
```

Output and state live in `~/.local/state/skill-map/` (`build/`, `published/`,
`published.prev/`); nothing else is written.

## Tests

```bash
python3 -m pytest -q ai/skill-map/tests
```

Run in a throwaway `HOME` with a made-up setup (plugins, claude.ai folders, a
vault, a project, session logs); opening a network socket fails the test. The
variable `SKILL_MAP_MANAGED_DIR` exists for the tests only (instead of
`/etc/claude-code`). The page itself is checked by hand: a fixture build served
locally, in light and dark mode and at 375 px width.

The design is `docs/superpowers/specs/2026-10-18-skill-map-design.md`.
