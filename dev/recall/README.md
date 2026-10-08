# recall — one hotkey for the commands, procedures and texts you forgot

You build tools with many options, then forget how to drive them. You write
procedures down, then can't find them. Agents leave commit and merge request
texts in files, and copying them means `cat <file> | wl-copy`.

`recall` puts all of that into one fuzzy-searchable list:

| Mark | Entry | Enter does |
|------|-------|------------|
| ✎ | prepared text from `<repo>/.reviews/` (newest first) | copies the content, shows a desktop notification, quits |
| ⌘ | command from your Markdown command table | copies the command (no trailing newline), quits |
| ☰ | procedure or how-to note | shows it rendered with `glow` (fallback `bat`); `q` returns to the list |

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

In the list: `enter` use · `alt-enter` ask assistant · `f1` help · `esc` quit.
The preview on the right shows the file (Markdown rendered by `glow`), or a
command's explanation and keywords; `f1` swaps it for the key help and back.

## Requirements

- Bash, `fzf`, `bat`, `wl-copy` (Wayland), optional `notify-send`
- Optional `glow` to render Markdown notes (headings, tables, bold) instead of
  showing their source; `GLOW_STYLE` picks its style
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
ptyxis -s --new-window -T recall -- recall
```

recall itself does not care which terminal opens it.

## Command table format

```markdown
## git

| Command | Explanation | Keywords |
|---|---|---|
| `git log --oneline \| head` | last commits, short | history |
```

Rows with exactly three cells count; header and separator rows are skipped,
surrounding backticks are removed, `\|` becomes `|`, and the `##` heading is
added to the keywords. Keywords are shown dimmed so fzf can search them.

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
`notify-send` and `claude`; needs `jq`.
