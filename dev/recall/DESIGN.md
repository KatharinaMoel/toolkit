# recall — design of the grouped list and the text lifecycle

Status: agreed 2026-10-09 after the first hand test. Implemented in `recall`.
The footer holds the key hints on two short lines, so they fit a narrow window.

## Problem

The first version showed every prepared text (✎), command (⌘) and procedure (☰)
in one flat list — about a hundred entries after two days. Three kinds of content
with different jobs sat side by side:

- one-off texts: copy once, then useless
- short commands: meant to be learned, like a man page
- long procedures: read now and then, must stay current

And prepared texts never went away.

## List

**Empty search → grouped view.**

```
› _
  ✎ projekt-a (8) ▾          repo of the start directory, else the newest
      commit-msg-feature-….txt
  ✎ projekt-b (2) ▸
  ✎ parked (3) ▸             texts on their way to the trash
  ⌘ wt  Worktrees (9) ▸      one group per "## tool — subtitle" heading
  ☰ runbooks (10) ▸          one group per PROCEDURE_GLOBS entry
────────────────────────────
 tab open/close · enter use · ctrl-o open · ctrl-k keep · …
```

- `tab` toggles the group of the current line; `enter` on a group line does the same.
- Only one text group is open at start: the repo of the start directory
  (`git rev-parse --show-toplevel`), else the repo with the newest text.
- The preview of a ⌘ group shows all its commands as a compact table: a cheat
  sheet without opening anything.

**Typing → flat search** over everything, as in the first version. Clearing the
search returns to the grouped view.

`recall texts` shows only the ✎ groups.

## Text lifecycle

States are computed on every start from five values; three are stored.

```
start     = max(file mtime, kept_at, first_seen)
hidden_at = copied_at > start ? copied_at + TEXT_HIDE_AFTER_COPY_DAYS (4)
                              : start     + TEXT_HIDE_UNUSED_DAYS     (7)
trash_at  = hidden_at + TEXT_TRASH_DAYS (7)

now < hidden_at  → active   (repo group)
now < trash_at   → parked   (group "parked", still found by typing)
otherwise        → due      (goes to the trash at the next start)
```

`first_seen` is when recall first listed the text. It protects every text that is
new to recall — all of them on the very first start, one restored from the trash,
one whose folder was away for a start — from being judged by an old mtime: its
clock starts when recall sees it. (Without it, a restored text went straight back
to the trash at the next start; found in review.)

- Copied texts are not hidden right away: a copy may have been a slip.
- Texts never copied (the commit was written elsewhere) age out as well.
- A rewritten file (new mtime) is fresh again.
- `ctrl-k` (keep) sets `kept_at = now` and brings a parked text back.
- Stored: `copied_at`, `kept_at` and `first_seen` per real path in
  `${XDG_STATE_HOME:-~/.local/state}/recall/texts.tsv`. Only the start writes new
  rows; rows of files that are gone are dropped. Renaming a repo folder therefore
  restarts the clocks of its texts — the safe direction.

**Cleanup at start, before the list opens:**

- due files go to the desktop trash with `gio trash <real path>`; the trash keeps
  the original location, so the file manager can restore them
- the real file is trashed, never a symlink in a worktree
- each action is one line in `trash.log` next to the state file; `f1` shows the
  last lines, the footer and a desktop notification name the count
- without `gio` (or when `gio trash` fails) nothing is deleted and the footer says
  so; such a text stays listed under "parked", so it can still be found or kept;
  recall never calls `rm` on a text
- `RECALL_NOW` (epoch seconds) replaces "now", for tests

## Procedures

- `enter` reads the note rendered (glow, as before).
- `ctrl-o` opens the file with `OPEN_CMD` (default `xdg-open`), also for texts.
- The preview starts with `updated <date>` from the front matter (`updated:`,
  else the file mtime) and adds `· older than STALE_DAYS days` (90) when it is.

## Window

recall cannot size its own window. Terminal launchers that know
`--maximize` (Ptyxis 50.1 does) get it in the hotkey command.

## Mechanism (fzf ≥ 0.74, verified in a pseudo-terminal on 2026-10-09)

- Each line is `<kind>\t<target>\t<group>\t<cursor id>\t<display>[\t<explanation>\t<keywords>]`;
  fzf shows field 5 and keeps the cursor on the same field 4 across a reload
  (`--id-nth=4 --track`). A group line's id is the group, every entry has its own
  (`f:<target>`), in both views. A shared id per group made `--track` jump to the
  first line with that id: after `ctrl-k` the next `enter` copied another text (flat
  list) or folded the group (tree) — both found with a real fzf in tmux. Folding from
  a child line therefore moves the cursor explicitly: `reload-sync(...)+wait+pos(N)`,
  N being the group's line in the rebuilt tree.
- Both views are cached as files in `RECALL_RUN`; a reload only `cat`s one
  (`cat "$RECALL_RUN/<view>.list"`, the path comes from the environment, so quotes
  or parentheses in TMPDIR cannot break the action string). fzf ignores `enter`
  while a reload runs, and building a list reads every source (about 0.2 s), so a
  reload that built the list swallowed an `enter` typed within 0.2 s of the first
  key. The current view is built before fzf starts, the other one in the
  background (it only fills a missing file, so a newer synchronous build wins);
  a reload that finds no file yet waits for it up to 0.5 s. `tab` and `ctrl-k`
  rebuild what they change. Measured with a real fzf: `enter` 0.02 s after typing
  is lost, 0.05 s works. Keys typed before fzf is up are lost, as with any fzf
  program: in tmux recall takes keys about 0.4 s after start (the first version
  about 0.3 s; the cleanup and the grouped list come first).
- The cached lists hold for one run: a copy or `ctrl-k` in a second recall window
  shows in the first only after its next rebuild (the preview reads the state live).
- At start the cursor sits on the first text of the open text group — the newest
  text of the start repo, else the newest of all — not on its group line
  (`load:pos(2)+unbind(load)`), so start + `enter` copies it, as in the flat list
  before. Not when that group was closed meanwhile, nor in a flat start after a
  question to the assistant (the best match is first there).
- `change:bg-transform(recall --on-change)` reloads only when the search switches
  between empty and non-empty (`FZF_QUERY` is visible to the command). It must be
  the background variant: a plain `transform` blocks fzf while it runs, and keys
  typed meanwhile are lost (typing `glab` fast gave `g`; measured in tmux). The price:
  two quick changes may be decided out of order, so in rare cases an empty search
  shows the flat list until the next key, or (after `tab`/`enter` on a group while
  the first key was still being decided) the groups stay while you type until the
  search is cleared once — harmless.
- `tab`, `enter` and `ctrl-k` call the synchronous `transform(recall --key <name> {})`
  (one key at a time; `enter` must decide before anything else happens); the script
  changes its own state and prints the fzf action (`reload-sync(...)` or
  `accept-or-print-query`). `enter` with a search text on a tree line means the
  switch to the flat list has not arrived yet: it prints
  `reload-sync(<flat>)+wait+first+accept-or-print-query`, so the best hit is taken.
  `enter` without a match still prints only the query, which asks the assistant.
- Per-run state (open groups, view mode, help flag) lives in a temporary
  directory, `RECALL_RUN`, removed on exit and before handing over to a full
  assistant session (`exec` skips the exit trap).
- Values for awk go through `ENVIRON`, not `-v`, which would read a backslash in a
  path as an escape. Text file names with a tab or newline are skipped: they cannot
  be one list line.

## Not included

Mouse support, a `## Kurz` excerpt, a "park now" key, a second assistant backend.
