# recall — one hotkey for the commands, procedures and texts you forgot

You build tools with many options, then forget how to drive them. You write
procedures down, then can't find them. Agents leave commit and merge request
texts in files, and copying them means `cat <file> | wl-copy`.

`recall` puts all of that into one list: grouped while the search is empty,
fuzzy-searchable as soon as you type.

| Mark | Entry | Enter does |
|------|-------|------------|
| ✎ | prepared text from `<repo>/.reviews/` (newest first) | copies the content, shows a desktop notification, quits |
| ⌘ | command from your Markdown command table | copies the command (no trailing newline), quits |
| ☰ | procedure or how-to note | shows it rendered with `glow` (fallback `bat`); `q` returns to the list |

```
› _
  ✎ my-repo (3) ▾              texts of the repo you started in (or the newest)
      commit-msg-feature-x.txt
  ✎ parked (2) ▸               texts on their way to the trash
  ⌘ git  Branches (6) ▸        one group per "## tool — subtitle" in the command file
  ☰ runbooks (10) ▸            one group per PROCEDURE_GLOBS entry
```

The cursor starts on the newest text of the open group, so the hotkey plus
`enter` copies it.
`tab` (or `enter` on a group) opens and closes a group. The preview of a ⌘ group
shows all its commands at once — a cheat sheet to learn from. Typing switches
to a flat search over everything; an empty search brings the groups back.

When nothing fits, the assistant answers: `alt-enter` (or `enter` without a
match) sends your search text to Claude Code — read-only, inside your notes.
After the answer, `n` continues the same conversation as a normal interactive
session.

## Usage

```bash
recall          # everything
recall texts    # prepared texts only
recall --help
recall --keys   # key help only
```

In the list: `tab` fold · `enter` use · `ctrl-o` open the file in its
application (`OPEN_CMD`, default `xdg-open`) · `ctrl-k` keep a text ·
`alt-enter` ask assistant · `f1` help · `esc` quit.
The preview on the right shows the file (Markdown rendered by `glow`), or a
command's explanation and keywords; texts start with their lifecycle state,
procedures with their `updated:` date (marked when older than `STALE_DAYS`).
`f1` swaps the preview for the key help and back.

## Prepared texts clean up after themselves

Texts in `.reviews/` are written for one use. recall parks them and later moves
them to the desktop trash — never deleting them outright:

| When | State |
|---|---|
| copied less than 4 days ago, or unused and changed less than 7 days ago | active, in its repo group |
| copied 4+ days ago, or unused for 7+ days | **parked**: group "parked", still found by typing |
| 7 days parked | moved to the trash with `gio trash` at the next start of recall |

- `ctrl-k` on a text keeps it: its clock starts again.
- A text new to recall starts its clock when recall first sees it, not at its
  file date. On the very first start nothing is trashed; old texts are parked a
  week later. A text restored from the trash gets a fresh clock the same way.
- Copy and keep times belong to the file path: renaming a repo folder restarts them.
- A file rewritten in place (new modification time) counts as fresh.
- recall stores only copy, keep and first-seen times, in `~/.local/state/recall/texts.tsv`;
  `trash.log` next to it lists what went to the trash, and `f1` shows the last ones.
- Get one back with `gio trash --list` and `gio trash --restore <trash:///...>`,
  or from the trash in the file manager.
- Without `gio` nothing is deleted; due texts stay listed as parked. The days are
  `TEXT_*_DAYS` in the config.

## Requirements

- Bash, `fzf` 0.74 or newer (the `wait` action; also `--footer`, `--id-nth`, `bg-transform`), `bat`, `wl-copy` (Wayland), optional `notify-send`
- `gio` (GLib, on any GNOME desktop) to move old texts to the trash
- Optional `glow` to render Markdown notes (headings, tables, bold) instead of
  showing their source; `GLOW_STYLE` picks its style
- The list uses calm 256-colour accents per kind (`COLOR_*`, `FZF_COLORS` in the config);
  `NO_COLOR=1` turns them off
- For the assistant: [Claude Code](https://code.claude.com) (`claude`) and `jq`

Fedora: `sudo dnf install fzf bat wl-clipboard jq libnotify glow`

## Setup

```bash
ln -s "$PWD/dev/recall/recall" ~/.local/bin/recall
mkdir -p ~/.config/recall
cp dev/recall/example.conf ~/.config/recall/recall.conf   # then edit paths
```

Bind a hotkey (GNOME: Settings → Keyboard → Custom Shortcuts), for example:

```bash
ptyxis -s --new-window --maximize -T recall -- recall
```

recall cannot size its own window; `--maximize` asks the terminal to (Ptyxis
50.1 lists the option). recall itself does not care which terminal opens it.
Started from a terminal inside a repo, recall opens that repo's texts first.

## Command table format

```markdown
## git — Branches

| Command | Explanation | Keywords |
|---|---|---|
| `git log --oneline \| head` | last commits, short | history |
```

Rows with exactly three cells count; header and separator rows are skipped,
surrounding backticks are removed, `\|` becomes `|`, and the tool name of the
`##` heading is added to the keywords. Text after ` — ` (or ` - `) in the heading
is the group's subtitle. Keywords are shown dimmed so fzf can search them.

## The assistant

```
claude -p "<question>" --session-id <uuid> --model sonnet --safe-mode \
  --tools Read,Grep,Glob --permission-mode dontAsk --add-dir <VAULT> ...
```

- runs in `VAULT`, can only read and search files, never asks for permissions
- `--safe-mode` skips your hooks, plugins and CLAUDE.md
- `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed for the call, so it
  uses your Claude Code login instead of switching to API billing
- `ASSIST_MODEL` (default `sonnet`) picks the model; empty uses Claude Code's default
- `n` resumes the session interactively with your normal settings

## Tests

```bash
bash dev/recall/test_recall.sh
```

Runs in a throwaway `HOME` with stubs for `fzf`, `bat`, `glow`, `wl-copy`,
`notify-send`, `gio` and `claude`, and a fixed "now" (`RECALL_NOW`) for the
lifecycle; needs `jq` and `git`. DESIGN.md explains the grouped list.
