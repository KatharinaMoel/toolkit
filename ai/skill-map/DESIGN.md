# skill-map (Skill-Landkarte) — design

Status: spec, written on 2026-10-18 from the user's decisions. Not implemented yet.
Target: `ai/skill-map/` in this repository.
Workflow for the builder: superpowers `writing-plans`, then implementation with TDD.
Everything the builder needs is below. The builder works without asking the user,
except at the points marked **needs the user's OK**.

Marking used in this spec (same as in `ai/skill-show/DESIGN.md`):

- **User decided**: the user chose this. Do not change it without asking.
- **Spec author decided**: chosen while writing the spec, with a reason. The builder
  may change it only for a concrete technical reason, and says so in the commit.
- **Observed**: seen on the author's machine on 2026-10-18. It is not documented by
  Anthropic and may change with a Claude Code update.

Inputs this spec builds on:

- `docs/superpowers/specs/assets/skill-map/prototype-v5.html`: the page as
  published today (version 5). Its lists, tables and usage numbers are typed in by
  hand; only the full texts come from `wortlaut.json` via `fetch`.
- `docs/superpowers/specs/assets/skill-map/build_wortlaut.py`: the one-off
  script that produced that `wortlaut.json`.
- `ai/skill-show/DESIGN.md`: the related tool. Its
  "Where it looks" table and "Precedence" rules are the reference for discovery here.
- The published page: a private claude.ai Artifact; its URL is the config key
  `artifact_url` (local, never in the repo).

## Intent and why

The user has a private page, the "Skill-Landkarte" (skill map), on claude.ai. It shows
where her skills, slash commands, vault runbooks, plugins and agents live, where they
come from, how often she uses them, and lets her read the full text of each file with
one click. Today the page is a snapshot: every list and number was typed in by hand,
so it goes stale as soon as a plugin updates or a runbook is added.

`skill-map` keeps the page current:

1. a build step reads the same places on disk and the session logs, and writes the
   data the page shows (`inventory.json`) plus the full texts (`wortlaut.json`);
2. the page builds all its lists from that data; only the narrative parts stay
   hand-written;
3. a SessionStart hook notices when the set of skills has changed and reminds the user
   with one line;
4. a vault runbook, `/landkarte-aktualisieren`, lets Claude rebuild, check and
   republish the page under the same URL.

The limit that shapes the design: **only Claude can publish** an Artifact (the
Artifact tool inside a Claude session). No script can upload the page. So the tool
prepares and checks everything locally, and the publish step is a runbook that Claude
runs with the user present.

## Goals

1. `skill-map build` writes `inventory.json`, `wortlaut.json` and the page
   `index.html` into a build folder, from local files only.
2. The inventory covers every entry the prototype shows: personal and project
   commands, personal skills, vault runbooks, installed plugins (skills, commands,
   agents), claude.ai-synced skills and plugins, Claude Code hooks, toolkit tools, and
   bundled Claude Code commands named in the config.
3. Each entry carries name, invocation, kind, group and place, origin (vendor,
   version, marketplace), description, path with `~`, runbook status and area, and
   usage (count and last date).
4. Texts in `wortlaut.json` are the file contents 1:1, or visibly withheld with a
   reason. Nothing is shortened or reworded.
5. The page renders all lists from `inventory.json` and keeps the prototype's design
   and interaction: lanes, cheat-sheet tables, lookup with search, viewer, copy
   buttons, cross-links (legend → lane, chip → group or viewer, table name → viewer).
6. Hand-written parts reference entries by key. A key that no longer exists is shown
   as missing on the page and reported by the build.
7. A fingerprint over the set of entries (without usage) is stored at publish time.
   `skill-map check`, run as a SessionStart hook, prints one line when the
   current set differs, and nothing otherwise.
8. `skill-map diff` tells Claude which texts are new or changed since the last
   publish, so they can be read before publishing.
9. Tests run with an artificial `HOME`, fixture files and fixture session logs, never
   against the real machine.

## Non-goals

- Publishing. The tool never uploads anything; the runbook does that through Claude.
- Editing, enabling or disabling skills, plugins or hooks.
- Changing `~/.claude/settings.json`. The spec describes the hook entry; the builder
  adds it only with the user's OK (see "Fingerprint and hook").
- Exact usage statistics. The counts are an approximation (see "Usage").
- Showing hook scripts, toolkit scripts or runbook files as full text (phase 1 lists
  them; their texts are not in `wortlaut.json`).
- A team version of the page. It is the user's private overview.
- macOS and Windows.

## Anti-goals (never)

- **Publishing unread text.** Every text that is new or changed since the last
  publish is read by Claude before the publish (runbook rule). The tool supports
  this; it never marks something as published by itself.
- **Personal data on the page.** Texts on the exclusion list (today: `timesheet`)
  and texts whose source is classified `sensitive` or `secret` never enter
  `wortlaut.json`. Session-log content never enters any output file; only counts and
  dates per known name do. Plugin author e-mail addresses are not copied.
- **Personal content in this repository.** The narrative, the config and all build
  output live outside the repo (repo principle "engine/config split"; the repo is
  shared on GitHub).
- **Network access** anywhere: no `curl`, no API, no `claude`, no `git fetch`. The
  hook in particular never touches the network.
- **A slow start.** The hook must not read the session logs or any full skill text,
  must finish well under 300 ms on the author's machine, and must never block,
  prompt or fail the session start.
- **Silent loss.** A referenced key that disappeared is marked, not dropped. A text
  that cannot be shown unchanged is withheld with a reason, not altered.
- **Altering texts.** No re-encoding, no trimming, no `errors="replace"`.

## Constraints

- **Python 3.12+, standard library only** (`json`, `tomllib`, `hashlib`, `pathlib`,
  `re`, `argparse`). Spec author decided: the prototype build is Python, the work is
  JSON- and text-heavy, and the repo already has a Python tool with pytest
  (`media/transcribe`). A bash tool would need `jq` per plugin and could not keep the
  hook under 300 ms as easily. No third-party packages, so no venv is needed.
- Folder layout (spec author decided, following `media/transcribe`):

  ```
  ai/skill-map/
    skill-map          launcher (bash): runs python3 -m skill_map with
                             PYTHONPATH=<this folder>/src, resolves its real path so a
                             symlink in ~/.local/bin works
    src/skill_map/     the package (module split left to the builder)
    page/template.html       the page, with slots for the narrative
    README.md                usage, requirements, setup, places, usage method, limits
    example.conf             anonymized config (TOML syntax, says so on line 1)
    example-erzaehlung.html  anonymized narrative example
    tests/                   pytest tests, conftest.py, fixtures/
  ```

  Unlike `transcribe`, the launcher uses `python3` from `PATH` (no venv). It must pass
  `bash -n` and `shellcheck`.
- Repo integration, part of phase 1:
  - row in the **Tools** table of the top-level `README.md` (area `dev`);
  - a CI job like the `transcribe` job: Python 3.12, `pip install pytest`, `bash -n`
    and `shellcheck` on the launcher, `python -m pytest -q ai/skill-map/tests`;
  - add `ai/skill-map/skill-map` to `is_ci_shell` in
    `.githooks/pre-commit` (its comment says to keep it in sync with `ci.yml`).
- Config: `${XDG_CONFIG_HOME:-~/.config}/skill-map/skill-map.conf`
  (TOML). Every key optional. Machine-specific values never go into the repo.
- State: `${XDG_STATE_HOME:-~/.local/state}/skill-map/` holds `build/`,
  `published/`, `published.prev/`. Nothing else is written anywhere.
- `$CLAUDE_HOME` means `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, as in the skill-show
  spec (the builder verifies `CLAUDE_CONFIG_DIR` once in the current docs).
- Explain-then-run (repo principle): `build`, `diff` and `mark-published` print each
  source they read or file they write to stderr with a short reason, e.g.
  `reading ~/.claude/plugins/installed_plugins.json  (which plugin versions are installed)`.
  `check` is the exception: it is silent unless there is something to report, because
  it runs on every session start.
- CLI messages, help and README in **English** (repo convention). The page and the
  hook line are **German** (the page is German today; the user gave the hook line in
  German).
- Setup like the other tools:
  `ln -s "$PWD/ai/skill-map/skill-map" ~/.local/bin/skill-map`.

## Decided by the user

- Place: `toolkit/ai/skill-map/`.
- Goal: the page stays current. Only Claude can publish (Artifact tool, same URL).
- A build writes `inventory.json` (all entries: name, invocation, kind, group/place,
  origin/vendor/version, description, path with `~`, status and area for runbooks
  from front matter `status`/`tags`, usage: count and last date) and `wortlaut.json`
  (texts 1:1). Configurable exclusions for personal texts (today `timesheet`).
  Account UUIDs in paths are replaced.
- `index.html` builds **all** lists (lane chips, cheat-sheet tables, lookup) from the
  data. Only the narrative parts stay hand-maintained: the flow "Ein Projekt-Vorhaben von
  Anfang bis Ende", "Wofür nehme ich was", "Was auffällt". They reference keys; a key
  that no longer exists is marked visibly instead of disappearing. Design and
  interaction of the prototype stay.
- Fingerprint: a hash over the set of (name, kind, place, version), **without**
  usage. Stored at publish time.
- SessionStart hook: **remind only**. Compares current and stored fingerprint and,
  when they differ, prints one line such as
  `Skill-Landkarte veraltet (neu: …, entfernt: …) – /landkarte-aktualisieren`.
  Fast (target < 300 ms), no network, silent when equal. The existing hooks in
  `~/.claude/settings.json` stay; the spec describes the addition, the builder makes
  it only with the user's OK, using the `update-config` skill.
- A vault runbook `~/notes/40-runbooks/landkarte-aktualisieren.md` (command
  `/landkarte-aktualisieren` via `kios sync`): build, name the differences, read the
  texts of new entries before publishing, exclude personal data, publish with the
  Artifact tool under the same URL with `files: {"inventory.json": …, "wortlaut.json": …}`,
  store the fingerprint. The builder creates it.
- Optional, low priority: per plugin a link to its vendor/repository page (from
  `plugin.json` `homepage`/`repository`), and a link to the Claude Code docs on skills
  and plugins.
- Later: the build uses `skill-show --tsv` once it exists; until then its own
  discovery with the same precedence rules as the skill-show spec.
- Tests by repo convention, with an artificial `HOME` and fixture session logs.

## Spec author decisions at a glance

The larger ones, with reasons in the sections below:

1. **The narrative and all personal settings live outside the repo**, in
   `~/.config/skill-map/`; `build` merges the narrative into `index.html`.
2. **One discovery function** serves both `build` and `check`, so the hook and the
   page can never disagree about what exists.
3. **Metadata only in `inventory.json`, text only in `wortlaut.json`.**
4. **Changed texts are detected by a per-entry text hash**, separately from the
   fingerprint, so the runbook re-reads edited texts even though the hook ignores
   them.
5. **Withhold instead of alter**: a text that is not valid UTF-8, contains an account
   UUID, or comes from a `sensitive`/`secret` note is withheld with a reason.

## Data model

### Keys

Every entry has a unique key. The page, the narrative, the usage counter and the diff
all use it. Spec author decided, extending the keys of `build_wortlaut.py` (which the
prototype already uses, e.g. `agent:pr-review-toolkit:code-reviewer`):

| Kind | Key | Example |
|---|---|---|
| personal/project command, personal/project skill | `<name>` | `kios-start`, `timesheet` |
| plugin or claude.ai skill/command | `<prefix>:<name>` (prefix = `plugin.json` `name`) | `superpowers:brainstorming`, `ai:building-pydantic-ai-agents`, `anthropic-skills:pdf` |
| agent (plugin) | `agent:<prefix>:<name>` | `agent:pr-review-toolkit:code-reviewer` |
| agent (personal, `$CLAUDE_HOME/agents/*.md`) | `agent:<name>` | none today |
| vault runbook | `runbook:<file stem>` | `runbook:mr-review` |
| hook | `hook:<event>:<command basename>` | `hook:SessionStart:session-start-boundary.sh` |
| toolkit tool | `tool:<name>` | `tool:wt` |
| bundled Claude Code command (from config) | `builtin:<name>` | `builtin:code-review` |

When two entries would get the same bare key (a personal command and a project command
both named `start`, a skill and a command both named `alpha`), the active one keeps
the bare key and the shadowed ones get `<key>@<place id>` and the flag `shadowed`.
"Active" follows the precedence in the skill-show spec (skills before commands,
personal before project). Spec author decided: keys stay stable for the common case,
and shadowed files are still visible, which is the point of the page.

### `inventory.json`

```json
{
  "schema": 1,
  "generated": "2026-10-18T14:30:12+02:00",
  "fingerprint": "sha256:3f9a…",
  "usage": {
    "since": "2026-09-04",
    "sessions": 239,
    "method": "Slash commands from <command-name> in user messages, skills from Skill tool calls, agents from Agent/Task tool calls; top-level session logs only; repeated messages counted once.",
    "unmatched": [{"name": "/model", "count": 10, "last": "2026-10-18"}]
  },
  "places": [
    {"id": "vault-runbooks", "title": "Runbooks im Vault", "path": "~/notes/40-runbooks/", "scope": "nur für dich · Quelle der Wahrheit", "color": "vault"},
    {"id": "personal-commands", "title": "Persönliche Commands", "path": "~/.claude/commands/", "scope": "nur für dich · in jedem Projekt", "color": "vault"},
    {"id": "plugins", "title": "Installierte Plugins", "path": "~/.claude/plugins/", "scope": "nur für dich · Aufruf mit Präfix plugin:", "color": "plugin"}
  ],
  "groups": [
    {"id": "plugin:superpowers", "title": "Plugin superpowers", "place": "plugins",
     "origin": {"type": "plugin", "plugin": "superpowers", "vendor": "Jesse Vincent",
                "version": "7.0.0", "marketplace": "claude-plugins-official",
                "installed": "2026-09-01", "homepage": "https://github.com/obra/superpowers",
                "repository": "https://github.com/obra/superpowers"},
     "counts": {"skill": 15, "command": 0, "agent": 0}}
  ],
  "entries": {
    "superpowers:brainstorming": {
      "name": "brainstorming",
      "call": "/superpowers:brainstorming",
      "kind": "skill",
      "group": "plugin:superpowers",
      "place": "plugins",
      "desc": "You MUST use this before any creative work …",
      "path": "~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.0/skills/brainstorming/SKILL.md",
      "runbook": null,
      "source_note": null,
      "usage": {"count": 22, "last": "2026-10-18"},
      "text": "shown",
      "text_sha256": "9c1e…",
      "flags": []
    },
    "mr-review": {
      "name": "mr-review", "call": "/mr-review", "kind": "command",
      "group": "personal-commands", "place": "personal-commands",
      "desc": "Einen GitLab-Merge-Request so vorbereiten …",
      "path": "~/.claude/commands/mr-review.md",
      "runbook": "runbook:mr-review",
      "source_note": "40-runbooks/mr-review.md",
      "usage": {"count": 4, "last": "2026-10-11"},
      "text": "shown", "text_sha256": "…", "flags": ["draft"]
    },
    "runbook:mr-review": {
      "name": "mr-review", "call": "/mr-review", "kind": "runbook",
      "group": "vault-runbooks", "place": "vault-runbooks",
      "desc": "Merge Request mit Claude Code reviewen",
      "path": "~/notes/40-runbooks/mr-review.md",
      "runbook": {"status": "entwurf", "tags": ["runbook", "review", "gitlab", "glab", "git"], "area": "Arbeit", "command": "mr-review", "command_entry": "mr-review"},
      "source_note": null,
      "usage": {"count": 4, "last": "2026-10-11"},
      "text": "none", "text_sha256": null, "flags": ["draft"]
    },
    "timesheet": {
      "name": "timesheet", "call": "/timesheet", "kind": "skill",
      "group": "personal-skills", "place": "personal-skills",
      "desc": "Arbeitszeiten eintragen und auswerten …",
      "path": "~/.claude/skills/timesheet/SKILL.md",
      "runbook": null, "source_note": null,
      "usage": {"count": 0, "last": null},
      "text": "withheld", "text_sha256": "…", "flags": ["withheld"]
    }
  },
  "narrative": {"missing_keys": ["superpowers:old-skill"]}
}
```

Field rules:

- `call`: the invocation the user types (`/name`, `/prefix:name`); for agents the
  `subagent_type` value (`pr-review-toolkit:code-reviewer`, no slash); for hooks the
  event name; for tools the command name; for a runbook its `command:` with a slash,
  or `null` when it has none.
- `kind`: `skill`, `command`, `agent`, `runbook`, `hook`, `tool`, `builtin`.
- `desc`: front matter `description:` of the file (first block only). Runbooks: the
  front matter `title:`. Hooks: the `statusMessage`, else empty. Tools: the first
  line of their README after the `#` heading's text (`wt — disposable git worktrees …`
  → the part after ` — `). Builtins: from config. Never shortened in the data (the
  page clamps it with CSS, as the prototype does).
- `path`: `$HOME` replaced by `~`; every account UUID and UUID pair (pattern of
  `build_wortlaut.py`: `[0-9a-f]{8}-[0-9a-f-]{27}(_[0-9a-f]{8}-[0-9a-f-]{27})?`)
  replaced by `<konto>`. The same replacement applies to every other path-like field
  (`places[].path`, `origin.*` paths). Builtins have `path: null`.
- `origin` (groups): `vendor` is `author.name` from `plugin.json` (string or object;
  never `author.email`). `version`: the `version` of the entry in
  `installed_plugins.json` (observed: holds a short git SHA when `plugin.json` has no
  version, e.g. `ea10b213686c` for `pr-review-toolkit`), else `plugin.json` `version`,
  else `null`. `installed`: date part of `installedAt`. claude.ai plugins:
  `version: "g<generation>"`, `marketplace: null`, `type: "claude.ai"`. `homepage` and
  `repository`: only when the value is an `https://` or `http://` URL, else `null`
  (observed: `repository` can be `null`).
- `runbook` (runbook entries): `status` and `tags` from front matter, `command` from
  front matter `command:` (observed: written without slash, e.g.
  `command: arbeit-verteilen`), `command_entry` the key of the generated command if
  one exists, else `null` and the flag `no-command`. `area`: the first tag that has a
  value in the config table `[areas]`, else `null` (the page then shows the tags).
  Command entries generated from a runbook carry `runbook: "<runbook key>"` (string)
  and inherit `draft` when the runbook's status is `entwurf`.
- `source_note`: the raw kios marker value (`40-runbooks/x.md`, `templates/x.md`),
  found as in the skill-show spec: `kios:generated | Quelle: ` within the first 2000
  bytes, value up to the next ` |`. Resolved against config `source_roots`; when no
  root has the file, the flag `source-missing` is set (the prototype strikes these
  through: the old `/start`, `/merken` … in the app repo).
- `usage`: see "Usage". Runbook entries copy the usage of their `command_entry`.
- `text`: `shown` (text is in `wortlaut.json`), `withheld` (a placeholder with reason
  is), `none` (kind has no text in phase 1: runbook, hook, tool, builtin).
- `text_sha256`: SHA-256 of the file bytes, also for withheld texts (so a change is
  noticed without publishing the text); `null` for `none`.
- `flags`: any of `draft`, `shadowed`, `disabled` (plugin set `false` in
  `enabledPlugins`), `withheld`, `no-command`, `source-missing`.
- `usage.unmatched`: names seen in the logs that match no entry, with count and last
  date; only names matching `^/?[A-Za-z0-9._:-]{1,80}$` (anything else is ignored, so
  no free text from logs can leak). Shown on the page as one dimmed line, helps the
  user notice bundled commands worth adding to `builtins`.
- `narrative.missing_keys`: keys referenced in the narrative that are not in
  `entries` (see "Page behaviour").
- Order: `places` in the fixed order of the lanes (below); `groups` by place, then
  title; `entries` sorted by key (stable output makes diffs readable).

### `wortlaut.json`

```json
{
  "schema": 1,
  "generated": "2026-10-18T14:30:12+02:00",
  "entries": {
    "superpowers:brainstorming": {"text": "---\nname: brainstorming\n…"},
    "timesheet": {"withheld": "Der Wortlaut wird hier bewusst nicht gezeigt: Der Skill enthält persönliche Angaben. Volltext lokal: ~/.claude/skills/timesheet/SKILL.md"}
  }
}
```

- Only entries with `text` `shown` or `withheld` appear. Each has exactly one of
  `text` (the file decoded as UTF-8, unchanged) or `withheld` (German reason plus the
  local path).
- Spec author decided — metadata is not repeated here (the prototype's
  `wortlaut.json` had `group`, `call`, `kind`, `path`, `source`, `desc`). One source
  of truth for metadata; `wortlaut.json` can be loaded after the lists render.

### Withholding rules (in this order; the first that applies sets the reason)

1. Key in config `withhold_text` → reason from config or the default sentence
   ("enthält persönliche Angaben"). Today: `timesheet` (user decided).
2. The file, or the kios source note of a generated command, has front matter
   `classification: sensitive` or `classification: secret` → "als vertraulich
   eingestuft". Spec author decided: this is the vault's own marking (CLAUDE.md rule 5);
   a command generated from a sensitive runbook carries the same text.
3. The file is not valid UTF-8 → "keine gültige UTF-8-Datei, Wortlaut nicht
   unverändert darstellbar".
4. The text contains an account UUID (the pattern above) → "enthält eine Konto-ID".
   Spec author decided: texts are never altered, so the only safe option is to
   withhold.

Config `hide` (list of keys or glob patterns over keys) removes entries completely:
not in `inventory.json`, not in `wortlaut.json`, not in the fingerprint. For things
the user does not want listed at all.

## Build behaviour

### Command line

```text
skill-map build [--out DIR]     write inventory.json, wortlaut.json, index.html (default DIR: <state>/build)
skill-map diff [--texts]        compare <state>/build with <state>/published; --texts prints the full texts to read
skill-map mark-published        after a successful publish: rotate published -> published.prev, copy build -> published
skill-map check                 hook mode: one line when the set changed, else nothing; always exit 0
skill-map fingerprint           print the current fingerprint and the sorted set it is computed from
skill-map --help
```

Exit codes: 0 done; 1 runtime error (unreadable required file, invalid JSON in
`installed_plugins.json`), message names the path; 2 usage or config error (unknown
subcommand, invalid TOML, wrong type in a config key). `check` always exits 0.

### Places it reads (discovery)

Same places and rules as the skill-show spec, "Where it looks", groups 1–10 (managed,
personal skill, project skill, extra-dir skill, personal command, project command,
claude.ai skill, installed plugin, claude.ai plugin), with these differences:

- **Project places come from config `projects`, not from the current directory.**
  Each project is `{path = "~/projects/app", label = "App-Repo"}`. Its
  `.claude/commands/*.md` and `.claude/skills/*/SKILL.md` are read. Spec author
  decided: the page and the fingerprint must be the same wherever a session starts;
  a cwd-based project would make the hook report changes just because the user
  started in another repo. Nested and extra-dir skills (skill-show groups 4 and 5) are
  skipped for the same reason.
- Additionally:
  - **agents**: `<installPath>/agents/*.md` of installed plugins (as
    `build_wortlaut.py`) and `$CLAUDE_HOME/agents/*.md`;
  - **vault runbooks**: `<vault>/40-runbooks/*.md` (config `vault`, no default: without it there
    are no runbook entries), skipping files that start with `_` (observed: `_guide.md`), front
    matter only (no text in `wortlaut.json`);
  - **hooks**: the `hooks` object of `$CLAUDE_HOME/settings.json` and of
    `<project>/.claude/settings.json` for each configured project: one entry per
    `type: command` hook with event, matcher, command path (with `~`), statusMessage;
  - **toolkit tools**: config `tools` (glob, e.g. `~/GitRepos/toolkit/dev/*/`): each
    folder that contains an executable file of the folder's name;
  - **builtins**: config `[builtins]` table, name → German description (e.g.
    `code-review = "Review des aktuellen Diffs"`). The prototype lists `/code-review`
    as "eingebaut in Claude Code"; bundled skills have no file (skill-show spec,
    "Not found and bundled skills").
- Rules taken over unchanged: skip dot entries (`.trash`, `.bucket-*`); plugin prefix
  from `plugin.json` `name` (observed: `pydantic-ai` → `ai`); only the installed
  version via `installPath`, never the cache; claude.ai plugins via
  `manifest.json` generation, else the folder with `.in_use`, else skip with a note
  on stderr; claude.ai skills via their manifest, prefix `anthropic-skills`
  (observed, config `synced_skill_prefix`); disabled plugins listed with the flag
  `disabled`; skill name from `name:` front matter, else the folder name.
- Missing places are normal and produce no message. A malformed
  `installed_plugins.json` is an error (exit 1), as plugins are a core part of the page.

### Fixed place list (lane order)

| id | Title (German, as in the prototype) | Colour token |
|---|---|---|
| `vault-runbooks` | Runbooks im Vault | `vault` |
| `personal-commands` | Persönliche Commands | `vault` |
| `plugins` | Installierte Plugins | `plugin` |
| `claude-ai` | Von claude.ai synchronisiert | `synced` |
| `personal-skills` | Eigene Skills | `vault` |
| `project:<n>` | label from config | `repo` |
| `toolkit` | toolkit | `cli` |
| `hooks` | Hooks | `muted` |
| `builtins` | Eingebaut in Claude Code | `muted` |
| `managed` | Verwaltet (Organisation) | `muted` |

`scope` texts (the small line under the path) are fixed strings in the tool, taken
from the prototype. Places without entries are left out.

### Usage

Counting as done ad hoc today (user's description), made precise. Spec author
decided where marked.

- Files: `$CLAUDE_HOME/projects/*/*.jsonl` — **top-level session logs only**, not
  `<session>/subagents/*.jsonl` (observed: 239 top-level and 294 subagent logs).
  Spec author decided: matches today's numbers, and a skill loaded inside a subagent
  was usually triggered by something the user already called.
- Each line is parsed as JSON; lines that fail are skipped and counted (one note on
  stderr with the number, no content).
- **Slash commands**: lines with `type == "user"`; `message.content` is a string or a
  list of parts with `text`; every `<command-name>NAME</command-name>` counts.
  Observed: `NAME` includes the leading slash (`/kios-shutdown`,
  `/superpowers:brainstorming`). Strip one `/`, then map: `prefix:name` → that key;
  bare `name` → the active entry with that bare key, else `builtin:<name>`, else
  `unmatched`.
- **Skills**: lines with `type == "assistant"`; every item of `message.content` with
  `type == "tool_use"`, `name == "Skill"` counts `input.skill`, mapped the same way.
- **Agents**: same, with `name in ("Agent", "Task")`, counts `input.subagent_type` as
  `agent:<value>`; built-in agent types without a file (`Explore`,
  `general-purpose`) go to `unmatched`.
- **Last date**: the line's `timestamp` (ISO 8601, observed with `Z`), converted to
  the local time zone, date part. `usage.since`: the earliest timestamp of any
  counted file; `usage.sessions`: number of files read.
- **Repeated lines counted once** (spec author decided): a line whose `uuid` was
  already seen (in any file) is skipped. Resumed or forked sessions may copy earlier
  messages into a new file; skipping by `uuid` removes that kind of double count.
  Remaining approximation (README states it): a slash command that loads a skill can
  appear as both a `<command-name>` and a `Skill` call; old logs are deleted by Claude
  Code after `cleanupPeriodDays` (not set in the user's settings today, so the
  default applies; the builder looks up the default in the current docs and names it
  in the README with the date checked).
- Performance hint (left to the builder): only parse lines that contain
  `<command-name>`, `"Skill"`, `"Agent"` or `"Task"` as substrings; the logs are
  large (observed ≈ 1.7 GB under `projects/`, including subagent logs).
- Privacy: nothing from the logs is written except per-key counts and dates and the
  `unmatched` names filtered by the regex above.

### Narrative merge

The narrative is the user's own HTML fragment file
`~/.config/skill-map/erzaehlung.html` (config `narrative`, default that path).
Spec author decided — **outside the repo**: it is personal (her projects, her
recommendations), and the repo's engine/config split forbids that content in the repo.
The repo ships `example-erzaehlung.html` with neutral content that exercises every
feature.

Format (all parts optional):

```html
<section data-slot="ablauf"> … the flow cards, as in the prototype … </section>
<section data-slot="chain"> … "Superpowers in einem Bild" … </section>
<section data-slot="wofuer"> … use-case cards … </section>
<section data-slot="auffaellig"> … "Was auffällt" … </section>
<section data-slot="repo-wissen"> … table "App-Repo: Wissen und Absicherung" … </section>
<template data-lane-note="vault-runbooks">Ändern immer hier, nie in der erzeugten Datei. …</template>
<script type="application/json" data-kurz>{"superpowers:brainstorming": "Fragen stellen, bis klar ist, was gebaut wird"}</script>
```

- References: any element with `data-key="<entry key>"` (usually `<code>`). Optional
  `data-copy="<text>"` overrides the copied text (the prototype copies
  `/board-check --nur-lesen`).
- `data-kurz`: short German descriptions for table rows, by key. Where a key has no
  short text, the table shows `desc`.
- `build` copies `page/template.html` to `<out>/index.html` and puts each
  `data-slot` section at the matching `<!-- slot:<name> -->` marker. Slots without a
  section stay empty and their heading is not shown. Lane notes and `data-kurz` are
  embedded as a `<script type="application/json" id="narrative">` block.
- `build` collects every key used in `data-key`, `data-lane-note` (place ids) and
  `data-kurz`, writes the unknown ones to `inventory.json` `narrative.missing_keys`
  and prints them on stderr (`narrative: 1 reference to a missing entry:
  superpowers:old-skill`). Not an error: the page shows them.
- Spec author decided — **merge at build time** rather than fetching a third file:
  the user decided the publish call carries two data files; the narrative then is part
  of the page Claude reads before publishing; and broken references are found before
  the publish.
- The narrative is trusted (her own file) and inserted as HTML. Everything from
  `inventory.json` and `wortlaut.json` is inserted with `textContent` only (third-party
  plugin descriptions must never become markup).

## Page behaviour

`page/template.html` starts from `prototype-v5.html` and keeps: the design tokens
(`:root` colours, dark mode under `prefers-color-scheme` guarded by
`:root:not([data-theme="light"])` and again under `:root[data-theme="dark"]`), fonts
(Google Fonts link as in the prototype), layout, the lane look, flash animations,
`prefers-reduced-motion` handling, the viewer dialog (focus handling, Escape, click
outside), copy buttons with clipboard fallback, the search, and the 720 px / 640 px
breakpoints. No external scripts.

### From data

- **Header**: title, lede with the date of `generated` ("Stand 18.10.2026"), legend
  built from the places present (each a link `#lane-<id>`), plus the fixed
  "gestrichelt = Entwurf" tag.
- **Banner**, only when `narrative.missing_keys` is not empty: "N Verweise im
  handgeschriebenen Text zeigen auf Einträge, die es nicht mehr gibt: …" with the keys.
- **"Wo was liegt"**: one lane per place (`id="lane-<id>"`), with title, path, scope,
  the lane note from the narrative if any. Chips:
  - runbooks, commands, personal skills, project commands, toolkit tools, hooks,
    builtins: one chip per entry; `draft` → dashed, `source-missing` → struck through
    (`.chip.stale`), `shadowed` → struck through with a title "überdeckt von …";
    `no-command` → small note "noch kein Command";
  - plugins and claude.ai: one chip per group, label `<plugin> (<n> Skills, <m>
    Agenten)` (zero counts left out), `disabled` → dimmed with "(aus)"; prefix shown
    when it differs from the folder (`pydantic-ai (Präfix ai:)`).
  - Chip click: entry with text → viewer; group chip → its lookup group (as
    `goGroup` in the prototype); entry without text → its lookup row.
  - The flow line "↓ kios sync erzeugt daraus Commands" between the vault-runbooks and
    personal-commands lanes is fixed page text, shown only when both lanes exist.
- **Cheat sheet** (spec author decided, replacing the hand-curated tables):
  - "kios" table: personal commands whose `source_note` starts with `templates/`;
  - "Runbooks" table: one row per runbook, columns Befehl (its command, or the stem
    with "noch ohne Command"), Was er tut, Bereich (area or tags), Status, Aufrufe ·
    zuletzt;
  - one table per plugin group with at least one entry; columns Befehl/Skill/Agent,
    Was er tut, Aufrufe · zuletzt; caption with vendor, version, marketplace, install
    date (and links, see "Later");
  - "Weitere installierte Plugins ohne eigene Befehle: …" as one line, as in the
    prototype;
  - one "claude.ai" table: one row per package with its skill names and vendor;
  - "Eingebaut" table from `builtins`; one table per project place;
  - rows sorted by usage count (descending), then name; zero usage shown dimmed as
    `0` (`.use.zero`); the cheat-sheet intro states `usage.since` and that the counts
    are an approximation;
  - first column: the name as a viewer link when it has text, plus a copy button
    with `call` (or the narrative's `data-copy`); "Was er tut" from `data-kurz`, else
    `desc`.
- **Nachschlagen**: one collapsible group per `groups` entry that has entries with
  text or metadata, summary with title, origin line and count; items with call (link),
  kind label and description; search over call, desc and kind (as the prototype).
  Entries with `text: none` open the viewer with metadata only and no "Text kopieren".
  Withheld entries open the viewer with the reason, marked as withheld.
- **Viewer**: title `call`, meta line `kind · origin · path`, description, text from
  `wortlaut.json`. Before `wortlaut.json` has loaded, the viewer says "Text wird
  geladen …"; if it fails: "Die Texte konnten nicht geladen werden …" (prototype
  wording), lists stay usable.
- **"Aktuell halten"** (fixed page text with data): date of the build, short
  fingerprint, "aktualisieren mit `/landkarte-aktualisieren`", the `unmatched` line.
- **Footer**: the places read, from `places[].path`.

### Hand-written (narrative slots)

"Ein Projekt-Vorhaben von Anfang bis Ende", "Superpowers in einem Bild", "Wofür nehme ich
was", "Was auffällt", and the app-repo table of files (`AGENTS.md`, `CONTRIBUTION.md`,
… — not skills, so not in the inventory). The builder moves today's content from
`prototype-v5.html` into the user's `erzaehlung.html`, replacing the hard-coded
`ALIAS`, `GROUP` and `ENTRY` maps of the prototype with `data-key` attributes. Spec
author decided: the "Superpowers in einem Bild" chain stays hand-written, because its
order is a judgement, not data.

### Missing keys

An element whose `data-key` is not in `entries`:

- keeps its text, gets the class `gone` (struck through, `--draft` colour, dashed
  outline) and a small label "nicht mehr vorhanden" after it;
- gets no link and no copy button;
- is listed in the banner at the top.

A `data-lane-note` for a missing place is not shown and is listed in the banner. A
`data-kurz` key that is missing only appears in the banner. Spec author decided: the
visible mark is the user's requirement; the banner makes sure she sees it without
scrolling.

### Robustness

- `inventory.json` fails to load → one message in place of the lists ("Die Daten
  konnten nicht geladen werden. Fehlt inventory.json neben der Seite?"), narrative
  still shown.
- An unknown `schema` value → the same message naming the version; no partial guess.

## Fingerprint and hook

### Fingerprint

- Input: for every entry (after `hide`), the tuple `(key, kind, place, version)`,
  where `version` is the group's `origin.version` for plugin and claude.ai entries
  and empty otherwise. "Fundort" (user's word) is represented by `place` plus the key;
  the plugin version covers the install path change on update. Spec author decided:
  the full path would change with every cache path detail without the user seeing a
  difference on the page.
- Encoding: one line per tuple, fields joined by tab, lines sorted, joined by `\n`,
  UTF-8, SHA-256, written as `sha256:<hex>`.
- **Not in it**: usage (user decided), texts and descriptions. Consequence (README
  states it): editing a runbook or a command's text does not trigger the reminder;
  the next `/landkarte-aktualisieren` still picks it up via `text_sha256` (see Open
  questions).
- Computed by the same discovery code as `build`, but without reading full texts or
  logs (front matter reads stop at the closing `---` or 4 KiB).

### Stored state

`mark-published`:

1. refuses (exit 1) when `<state>/build/` is missing, or when the current fingerprint
   differs from the one in `build/inventory.json` ("the set changed since the build;
   run build again"), so a stale build is never marked as published;
2. moves `published/` to `published.prev/` (replacing it) and copies `build/` to
   `published/`;
3. writes `published/fingerprint.json`:
   `{"fingerprint": "sha256:…", "set": [["superpowers:brainstorming", "skill", "plugins", "7.0.0"], …], "published": "<ISO time>"}`;
4. prints what it did (explain-then-run).

It does not know whether the publish worked; the runbook calls it only after the
Artifact tool reported success.

### `check` (hook mode)

- Does not read stdin (Claude Code passes hook JSON there; it is not needed, and a
  manual run in a terminal must not hang). Spec author decided.
- Reads config, runs discovery (no logs, no full texts), loads
  `published/fingerprint.json`.
- Equal → no output, exit 0.
- Different → one JSON object on stdout, the same shape as
  `~/.claude/hooks/session-start-boundary.sh` uses:
  `{"systemMessage": "Skill-Landkarte veraltet (neu: superpowers:x, runbook:y; entfernt: z; geändert: superpowers 7.0.0→7.1.0) – /landkarte-aktualisieren"}`.
  Names: at most 3 per part, then `+N`; parts without names are left out; "geändert"
  is the same key with a different version, shown once per group.
- No stored fingerprint yet → `Skill-Landkarte: noch nie veröffentlicht – /landkarte-aktualisieren`.
- Any error (unreadable config, broken `installed_plugins.json`) → one line
  `Skill-Landkarte: Prüfung fehlgeschlagen (<short reason>)`, exit 0. Spec author
  decided: the repo says "no silent fallbacks", and the hook must never break the
  session start; one visible line satisfies both.
- Only `systemMessage`, no `additionalContext`. Spec author decided: the reminder is
  for the user; putting it into the model's context would invite the model to start a
  refresh nobody asked for. Builder: verify in the current hooks docs that a
  SessionStart command hook may print `systemMessage` JSON (the existing hook relies
  on it, which is evidence but not proof).
- Performance: target < 300 ms wall time on the author's machine
  (`time skill-map check`), measured by the builder and written in the README
  with date and number. Python start plus about 20 small JSON reads and a few
  directory listings should fit; if not, the builder may cache per-plugin metadata
  keyed by `installed_plugins.json` mtime in the state folder (and documents it).

### Adding the hook (needs the user's OK)

The builder proposes this addition to `~/.claude/settings.json` and applies it only
after the user agrees, with the `update-config` skill. The existing entries
(`session-start-boundary.sh` under `SessionStart`, `stop-kurz-gesagt.py` under
`Stop`) stay unchanged:

```json
"SessionStart": [
  { "hooks": [ { "type": "command", "command": "/home/me/.claude/hooks/session-start-boundary.sh", "timeout": 10, "statusMessage": "Startort und Modus prüfen" } ] },
  { "matcher": "startup",
    "hooks": [ { "type": "command", "command": "/home/me/.local/bin/skill-map check", "timeout": 5 } ] }
]
```

- `matcher: "startup"`: remind once per new session, not again on resume, `/clear` or
  compaction. Builder: verify the SessionStart matcher values in the current docs.
- Absolute path, because hooks may run without the user's shell `PATH`.
- No `statusMessage`: a sub-second check does not need a status line (builder may add
  one if the user wants it).
- The README documents the snippet with `~` replaced by a placeholder; the repo never
  contains the user's absolute paths in code.

## Runbook /landkarte-aktualisieren

The builder creates `~/notes/40-runbooks/landkarte-aktualisieren.md` (vault, not
repo), then runs `kios sync` so that `/landkarte-aktualisieren` exists. It follows the
vault's runbook structure (observed in `40-runbooks/_guide.md` and the existing
runbooks): front matter, `## Auf einen Blick` directly after it, then `## Zweck`
(its first paragraph becomes the command description), `## Eingaben`, `## Eckdaten`,
`## Ablauf`, `## Entscheidungsregeln`, `## Ergebnis`, `## Historie`. German, like the
other runbooks.

Front matter:

```yaml
---
title: Skill-Landkarte aktualisieren
type: runbook
command: landkarte-aktualisieren
aliases: [skill-map, landkarte, skill-uebersicht]
tags: [runbook, claude-code, skills, entwicklung]
classification: internal
status: entwurf
secrets: []
context: [10-context/praeferenzen.md]
risk: aussen
rueckweg: Vorige Fassung liegt in ~/.local/state/skill-map/published.prev/ - mit denselben Schritten unter derselben URL erneut veroeffentlichen.
created: <date of creation>
updated: <date of creation>
source: manual
---
```

Content to write (in German, in the vault's style):

- **Auf einen Blick**: Aufruf `/landkarte-aktualisieren`; table `# · Befehl · wozu`:
  1. `skill-map build` — Daten und Seite neu erzeugen
  2. `skill-map diff` — was ist neu, weg, geändert
  3. `skill-map diff --texts` — neue und geänderte Texte lesen
  4. Artifact-Tool `read`, dann `publish` — unter derselben URL veröffentlichen
  5. `skill-map mark-published` — Fingerabdruck speichern
- **Zweck**: Die Skill-Landkarte auf claude.ai aktuell halten, wenn der
  SessionStart-Hook "Skill-Landkarte veraltet" meldet oder die Nutzerin es wünscht —
  ohne ungelesene oder persönliche Texte zu veröffentlichen.
- **Eingaben**: none required; optional a reason (hook line).
- **Eckdaten**: Artifact URL from config `artifact_url`;
  build folder `~/.local/state/skill-map/build/`; config
  `~/.config/skill-map/skill-map.conf`; narrative
  `~/.config/skill-map/erzaehlung.html`; tool in `~/GitRepos/toolkit/ai/skill-map/`.
- **Ablauf**:
  1. `skill-map build`; report errors and stop on exit ≠ 0.
  2. `skill-map diff`; tell the user the differences in plain words (new,
     removed, changed entries; missing narrative keys; withheld texts).
  3. `skill-map diff --texts`; read **every** printed text completely. Look for
     personal data: names of private persons, contract or time-account details,
     health, money, e-mail addresses, account IDs, tokens. Additionally run the
     secret scanner: `kios scan --stdin < ~/.local/state/skill-map/build/wortlaut.json`
     (exit 2 = probable secret → stop).
  4. Anything personal → propose a `withhold_text` (or `hide`) entry to the user,
     add it with her OK, back to step 1.
  5. Missing narrative keys → propose the change in `erzaehlung.html` to the user;
     change only with her OK (the narrative is her text). Publishing with marked
     missing keys is allowed when she says so.
  6. Read `build/index.html` completely (it contains the narrative and is published
     too).
  7. Artifact tool, `action: read` on the URL (the tool requires reading an artifact
     from an earlier conversation before updating it), then `action: publish` with
     `url` = the URL, `file_path` = `~/.local/state/skill-map/build/index.html`,
     `files` = `{"inventory.json": "<build>/inventory.json", "wortlaut.json": "<build>/wortlaut.json"}`.
     Never without `url` (that would create a new page). If the publish is refused
     because of a newer version, stop and tell the user; never use `force`.
  8. Only after a successful publish: `skill-map mark-published`.
  9. Add a line to `## Historie` (date, what changed).
- **Entscheidungsregeln**:
  - Nothing is published that was not read in this session or an earlier publish
    (unchanged `text_sha256`).
  - In doubt, withhold. Withholding is reversible, publishing is not.
  - No Artifact tool in this session → stop after step 6, do not run
    `mark-published`, tell the user.
  - The tool's numbers are approximations; say so if the user asks about them.
- **Ergebnis**: the page under the same URL shows the current state; the hook is
  silent again; `published.prev/` holds the previous version.
- Optionally (guide rule): a group `## landkarte-aktualisieren — Ablauf` in
  `70-resources/befehle.md` with the commands, so recall shows them.

Note on the Artifact tool: its behaviour above (read before update, `files` map, no
`force`) is how the tool described itself to the spec author on 2026-10-18. The
builder checks the tool's current description when writing the runbook and adapts
the wording; the rules "same URL" and "nothing unread" stay.

### `diff` details

- Compares `<state>/build/inventory.json` with `<state>/published/inventory.json`
  (missing published → everything is new).
- Prints three lists: new keys, removed keys, changed keys (any of `call`, `kind`,
  `place`, `origin.version`, `desc`, `text`, `text_sha256`, `flags` differ; the
  changed field names are shown), plus the missing narrative keys and the withheld
  entries with reasons.
- Also compares `build/index.html` with `published/index.html` by hash and says
  whether the page (template or narrative) changed.
- `--texts`: for every new or changed entry with `text: shown`, prints a header
  (`==> <key> · <path>`), the text unchanged, and an end line, like skill-show.
  Withheld texts are never printed.

## Test cases

`python -m pytest -q ai/skill-map/tests`, style of `media/transcribe/tests`
(`conftest.py` puts `src/` on `sys.path`). A shared fixture builds an artificial world
in `tmp_path` and sets `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`; unsets
`CLAUDE_CONFIG_DIR`. An autouse fixture replaces `socket.socket` with a function that
raises, so any network attempt fails the test. Launcher tests run the real launcher
via `subprocess` with that environment.

Fixture world (anonymized names, no real UUIDs except fixed fake ones):

- `~/.claude/commands/`: kios-generated commands with the marker on line 4 and 5
  (`templates/k-start.md`, `40-runbooks/rb-a.md`), one on line 1 in a project, a plain
  command, one whose source exists under no `source_roots`, one with CRLF line ends,
  one without final newline, one with invalid UTF-8, one containing the fake account
  UUID.
- `~/.claude/skills/`: `alpha/SKILL.md`, a symlinked skill folder, `zeit/SKILL.md`
  (listed in `withhold_text`), `.trash/old/SKILL.md`.
- `~/.claude/plugins/installed_plugins.json` (format observed:
  `{"version": 2, "plugins": {"<p>@<mkt>": [{"scope", "installPath", "version", "installedAt", …}]}}`)
  pointing to `cache/mkt/superp/7.0.0` (skills, `plugin.json` with homepage and an
  author e-mail), `cache/mkt/reviewkit/abc123def456` (no `plugin.json` version,
  agents, one command), `cache/mkt/pydantic-ai/0.1.0` (`plugin.json` name `ai`), a
  stale `cache/mkt/superp/6.0.0` with an extra skill; `settings.json` with one plugin
  disabled and two hooks.
- `~/.claude/skills/synced/<fake-uuid>_<fake-uuid>/` with `manifest.json` and
  `pdf/SKILL.md`; `~/.claude/plugins/synced/<fake-uuid>_<fake-uuid>/` with
  `manifest.json` generation 3, `eng/` (old) and `eng~g3/`.
- Vault `~/vault/40-runbooks/`: `rb-a.md` (status `aktiv`, tags with an area tag),
  `rb-b.md` (status `entwurf`, no generated command), `rb-c.md`
  (`classification: sensitive`, with a generated command), `_guide.md`.
- A project `~/proj` (in config `projects`) with `.claude/commands/` and a command
  that shadows a personal one; a toolkit folder with two tools.
- Session logs `~/.claude/projects/-proj/` (top level) and one under
  `<session>/subagents/`: `<command-name>` in string content and in list content, with
  and without slash, prefixed and bare; `Skill` calls bare and prefixed; `Agent` and
  `Task` calls with a plugin agent and with `Explore`; a line duplicated (same `uuid`)
  in a second file; a malformed line; a builtin (`/code-review`); a free-text
  `<command-name>` that fails the name regex; and a sentinel string
  (`SENTINEL-LOG-TEXT-7f3a`) in a user message.

Cases:

1. **Discovery**: every fixture entry appears once with the right key, kind, place,
   group, call, `~`-path; `.trash`, `_guide.md`, the stale plugin version and the old
   synced generation never appear; `ai:` prefix used; disabled plugin flagged;
   shadowed project command keyed `<name>@project:<n>` and flagged.
2. **Origin**: vendor from `author.name`; no e-mail anywhere in the output; version
   from `installed_plugins.json` (SHA for the plugin without version); `homepage`
   kept, a non-URL `repository` dropped.
3. **Runbooks**: status, tags, area mapping, `command_entry` link both ways, `draft`
   inherited by the generated command, `no-command` on `rb-b`, runbook usage equals
   its command's usage.
4. **kios source**: markers on lines 1, 4, 5 found; unresolvable source → flag
   `source-missing`.
5. **Texts 1:1**: for shown entries, `wortlaut.json` text encoded as UTF-8 equals the
   file bytes (CRLF and missing final newline included); `text_sha256` equals the
   file's SHA-256.
6. **Withholding**: `zeit` (config), the command of `rb-c` (sensitive source), the
   invalid-UTF-8 file and the UUID file are withheld with the right reason; their
   text is nowhere in `wortlaut.json`; `hide` removes an entry from both files and
   from the fingerprint.
7. **Account UUID**: the fake UUID string does not occur anywhere in
   `inventory.json` or `wortlaut.json`; paths show `<konto>`.
8. **Usage**: expected counts and last dates per key; subagent log ignored; duplicate
   `uuid` counted once; malformed line skipped with a count on stderr; `Explore` and
   `/code-review`-without-builtin-config in `unmatched`; with `code-review` in
   `[builtins]`, counted on `builtin:code-review`; free-text name dropped;
   `usage.since` is the earliest timestamp; the sentinel string occurs in no output
   file.
9. **Fingerprint**: equal for two builds; unchanged after adding log lines and after
   editing a command's text; changed after adding or removing an entry and after a
   plugin version bump; independent of file system listing order (shuffle by
   creating files in a different order).
10. **check**: no stored state → the "noch nie veröffentlicht" line; equal → empty
    stdout, exit 0; added/removed/version-changed → one JSON line whose
    `systemMessage` names them, at most 3 per part with `+N`; broken config → the
    "Prüfung fehlgeschlagen" line, exit 0; stdin is never read (run with a stdin that
    would block, e.g. an open pipe never written, under a timeout).
11. **check does not read logs or texts**: replace a session log with a FIFO and
    `chmod 000` a skill file; `check` still finishes (under a timeout) with the same
    result. A loose timing assertion (< 2 s for the fixture world) guards against
    accidental log scans in CI; the real target is measured manually (README).
12. **mark-published**: copies build to `published/`, rotates the previous one to
    `published.prev/`, writes `fingerprint.json`; refuses without a build; refuses
    when an entry was added after the build.
13. **diff**: new, removed and changed keys with changed field names; page change
    detected; `--texts` prints exactly the new/changed shown texts, unchanged
    between header and end line, and no withheld text.
14. **Narrative**: slots filled into `index.html`; unknown `data-key`,
    `data-lane-note` and `data-kurz` keys in `narrative.missing_keys` and on stderr;
    build without narrative file works (empty slots).
15. **Template hygiene** (static checks on `page/template.html`): contains every slot
    marker; contains no entry name from the user's real setup (e.g. no
    `brainstorming`, `kios-start`, a project name) — proves the lists come from
    data; `innerHTML` is used only in the narrative insertion function (grep count).
16. **Writes only its state**: SHA-256 list of every file under the fake `HOME`
    except `<state>` before and after `build`, `diff`, `check`, `mark-published` is
    identical.
17. **CLI**: `--help` exit 0; unknown subcommand exit 2; invalid TOML exit 2 with the
    path; missing `installed_plugins.json` is fine (no plugins), malformed one exit 1.
18. **Launcher**: works through a symlink; `bash -n` and `shellcheck` (CI).

Page rendering is checked by the builder by hand (no JS test setup in this repo):
serve a fixture build with `python3 -m http.server` in the build folder, open it,
check light and dark mode, 375 px width, search, viewer, copy buttons, a missing key
mark and the banner, and record that in the commit message. Then the same with the
user's real build before the first publish.

## Later

- **`skill-show --tsv`**: now that `ai/skill-show` exists, `build` takes skills and
  commands (skill-show groups 1–10) from `skill-show --tsv` (columns: invocation,
  kind, group, name, file, status, kios source, description) and keeps its own code
  only for what skill-show does not cover: agents, runbooks, hooks, tools, builtins,
  plugin origin (vendor, version, links) and usage. The `status` column maps to the
  flags `shadowed`/`disabled`. Points to check then: skill-show runs project lookup
  from the current directory, so `build` must call it with `--project <dir>` once per
  configured project; and `check` must stay under 300 ms — if one `skill-show --tsv`
  call is slower than that, `check` keeps the Python discovery and a test compares
  both results on the fixture world.
- **Links** (user decided, low priority): in group summaries and cheat-sheet
  captions, a link "Projektseite" to `origin.homepage`, else `origin.repository`
  (only `http(s)` URLs, `rel="noopener noreferrer"`, `target="_blank"`); in the
  "Aktuell halten" box links to the Claude Code docs on skills and plugins. The skill-show
  spec cites `code.claude.com/docs/en/skills` (read 2026-10-18); the plugins page URL
  was not checked by the spec author — the builder verifies both before adding them.
- Texts for hooks and toolkit tools in the viewer (would need the same read-before-publish
  care; hook scripts are the user's code).

## Left to the builder

- Module layout, function names, internal data structures, argparse details.
- Front matter parsing (a small parser for the first `---` block, keys
  `name`, `description`, `title`, `status`, `tags`, `command`, `classification`;
  flow lists `[a, b]` and quoted values as in the vault). No YAML library.
- Exact German strings on the page where the spec gives none; follow the prototype's
  tone.
- The cheat-sheet grouping details (for example whether small plugin groups are
  combined into one table like the prototype's "Prüfen und Aufräumen"), as long as
  every entry with a call appears in exactly one table.
- The README structure (follow `dev/recall/README.md`): usage, places, usage method
  and its limits, config keys, hook snippet, privacy rules, tests, measured `check` time.
- `example.conf` content: every key with a comment, anonymized paths
  (`~/notes`, `~/projects/app`).
- Writing the user's real config and `erzaehlung.html` from the prototype (outside the
  repo): the area table from the prototype's "Bereich" column (Arbeit, Entwicklung,
  Ehrenamt, Lernen, privat — the prototype says these were suggestions; keep them as
  they are and tell the user to check), `withhold_text = ["timesheet"]`, the configured
  project, the vault, the toolkit glob, the builtins the prototype names. Show the
  user the config before the first publish.
- Verifying the points marked "builder: verify" and recording results with the date in
  the README.

## Open questions

1. **Text edits and the reminder.** With the decided fingerprint (no texts), an edited
   runbook or an updated personal command does not make the hook speak; only adding,
   removing or a plugin version change does. The next refresh still re-reads changed
   texts. Is that what the user wants, or should the fingerprint include
   `text_sha256` (the hook would then read every skill file, still without logs;
   probably still under 300 ms, not measured)? The spec keeps the user's decision
   until she says otherwise.
2. **The prototype assets in the repo.** `docs/superpowers/specs/assets/skill-map/`
   is untracked today. `prototype-v5.html` contains the user's personal narrative and
   usage numbers, and the repo is shared on GitHub. Should the assets be committed
   with this spec, committed after anonymizing, or stay local? The builder needs the
   prototype locally either way; the spec does not depend on the answer.

## Resolved 2026-10-18 (user, via the session that wrote this spec)

- **Open question 1:** changed texts are reported, but as their own quieter hook
  line, not as "veraltet": for example `Skill-Landkarte: 2 Texte geändert –
  /landkarte-aktualisieren`. The fingerprint stays without texts; `check`
  additionally compares per-entry text hashes of the shown texts with the
  published ones. Builder: keep `check` under the time target; measure it.
- **Open question 2:** the prototype assets stay local
  (`docs/superpowers/specs/assets/` is in `.git/info/exclude`).
- Personal values (artifact URL, vault path, project names) were removed from this
  spec before its first commit; they belong in the local config.

## Revision 2026-10-18 (user decided): generic first, in `ai/`

The tool is built so that colleagues can use it for their own setup. This section
overrides the parts above where they differ.

- **Name and place:** `ai/skill-map/` (the `ai/` area holds tools that keep work
  with AI agents transparent; `ai/skill-show` is the sibling). Command
  `skill-map`, package `skill_map`, config
  `${XDG_CONFIG_HOME:-~/.config}/skill-map/skill-map.conf`, state
  `${XDG_STATE_HOME:-~/.local/state}/skill-map/`. The page may still be called
  "Skill-Landkarte": config `title` (default `Skill-Landkarte`), also used in the
  hook lines.
- **Zero config works:** without a config file, `build` shows everything at
  Claude Code's own places (skill-show groups 1–3 and 6–10, plugin agents,
  personal agents, hooks in `$CLAUDE_HOME/settings.json`) plus usage. Everything
  personal is an optional source switched on in the config: `vault` (runbooks
  folder and kios source notes), `source_roots`, `projects`, `tools`, `builtins`,
  `areas`, `withhold_text`, `hide`, `artifact_url`, `narrative`.
- **Public docs use neutral scenarios** ("if you keep runbooks in a notes vault,
  set `vault`"), never the author's real setup. The author's own values live only
  in her local config and narrative.
- **Two page outputs:** `build` writes `index.html` + `inventory.json` +
  `wortlaut.json` (for publishing as an Artifact, as above) **and**
  `skill-map.html`, one self-contained file with both JSON documents embedded as
  `<script type="application/json">` blocks, which opens from disk in any browser
  without a server and without claude.ai. The page uses embedded data when present,
  else fetches the files.
- **Phase 2 (not now):** `skill-map init` writes a commented config with what it can
  detect, and `SETUP.md` holds a prompt for Claude Code that asks the questions only
  a person can answer (own notes, what to hide, areas), writes the config and shows
  it for review.

## Revision 2026-10-19 (user decided): profiles for a second page

Need: a few texts the author withholds from her page (they name her team) should be
readable for exactly that team, while the first page stays as it is.

Options considered:

1. **Loosen `withhold_text` and republish the one page.** No code. Price: there is
   no page with the texts held back any more; who may read them then depends only on
   how that one page is shared.
2. **A second config file** (`--config team.conf`). Small change. Price: two files
   that drift apart (a new `hide` or `withhold_text` entry lands in one only).
3. **Profiles in the one config** (chosen). `[profiles.<name>]` overrides `title`,
   `artifact_url`, `refresh_hint` and releases keys from `withhold_text`; each
   profile has its own state folder `profiles/<name>/`. Price: one more concept in
   config and CLI, and `check` reads one more state folder per published profile.

Rules that come with it:

- `release_text` only removes keys from `withhold_text`; a key it names that
  `withhold_text` does not hold is a config error, so a typo cannot pass silently.
  Classification, unknown source, account id and UTF-8 rules stay as they are
  (fail closed): a profile can show less-guarded texts, never classified ones.
- Without `--profile`, folders and output are unchanged (checked byte for byte
  against a build from before the change, apart from `generated`).
- `check` nags about a profile only after its first `mark-published`, so defining
  a profile does not add a line before it exists online.
- With the default `refresh_hint`, a profile's line names `--profile <name>`; a
  hint set in the config (a slash command of one's own) is kept.
- `runbook_text` (top level or profile, default false): the page shows a runbook's
  whole file, not only its front matter. Need: the commands are short entry points
  that say "read the runbook first", so without it a reader of the team page sees
  the steps but not the rules. A runbook is held back by the `withhold_text` entry
  of its command (looked up by command name too, so hiding the command does not
  release it) and by its own classification. Price: on the first publish every
  runbook text is new and has to be read in full. Linked knowledge notes stay out
  (a separate decision).
