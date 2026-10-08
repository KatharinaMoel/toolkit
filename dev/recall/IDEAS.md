# recall — improvement ideas

Collected from the first hand test (week of 2026-10-09). Not scheduled; evaluate
at the end of the trial week (see the recall project note in the vault).

## 1. Prepared texts without typing a search term

Finding a commit message means typing `commit-message` first, which defeats
the point of a quick pick.

- Make the `✎` entries reachable in one step: a button / symbol in the window
  that switches the list to prepared texts (same as `recall texts`), clickable
  with the mouse.
- Make that switch reachable from the keyboard as well: `tab` moves between
  the kinds (all · texts · commands · procedures), the list is filtered by the
  chosen kind. Open question: fzf has no real buttons, so either key-bound kind
  filters with a visible header line, or a small clickable bar if the terminal
  supports mouse events (to be checked, not verified).
- The same switch applies to the other marked kinds (`⌘`, `☰`), not only `✎`.

## 2. Default window size 130 x 30 — parked, unsolved

The window is too small by default. The hotkeys (GNOME custom shortcuts custom3 / custom4)
start `ptyxis -s --new-window -T recall -- /home/katha/.local/bin/recall [texts]`.
`ptyxis --help-all` shows no geometry option (Ptyxis 50.1). Decision on 2026-10-08:
leave it for now and resize the window by hand; revisit later.

### What was tried (2026-10-08, Fedora, Ptyxis 50.1, Wayland)

Method: open a Ptyxis window, read the size with `tput cols; tput lines` (once from a
script inside the window, once by hand in a second tab of the real hotkey window).
Every attempt gave **80 x 24**.

| Attempt | Result |
|---|---|
| `org.gnome.Ptyxis window-size` = (130, 30), `restore-window-size` false | 80 x 24 |
| same with `restore-window-size` true | 80 x 24 |
| same, hotkey window opened right after setting the key (by hand) | 80 x 24 |
| with and without `-s` (standalone) | 80 x 24 |
| `default-columns` / `default-rows` (100 / 40 on this machine) | not applied, 80 x 24 |
| escape sequence `printf '\e[8;30;130t'` inside the window | ignored, stays 80 x 24 |

### Observations

- Ptyxis **overwrites `window-size` whenever a window closes** with that window's size.
  Setting it by hand is therefore lost after the next close; it behaves like "last
  closed size", not like a start value.
- An early screenshot of the recall window was clearly wider (about 1176 px) than the
  later 80 x 24 window (about 741 px). How that window got its size is unknown — it
  was not measured.
- None of foot, gnome-terminal, kitty, alacritty, wezterm, xterm, kgx is installed, so
  no terminal with a command-line size option was available to compare.

### Hypotheses (not verified)

- Windows opened with `--new-window -- <command>` may ignore the saved size.
- `restore-window-size` may only apply to windows without a command, or only to the
  non-standalone instance.
- A Ptyxis profile might carry a size — unknown, not found in `--help-all`.

### Next steps for a later session

1. Search the Ptyxis docs / source for how the initial size is chosen (verify, do not guess).
2. Try without `-s` and without `-- <command>` (start `ptyxis --new-window` and run
   `recall` inside) to see whether the saved size then applies.
3. If nothing helps: install a terminal with a size flag (for example foot — check its
   `--help` first), then switch only the two hotkeys to it.
4. Whatever works goes into `README.md` (hotkey section) and `example.conf`.

Settings state left behind: `restore-window-size` false, `window-size` back to (130, 30)
(may have been overwritten again by Ptyxis since).

## 3. Calmer visual hierarchy

Make entries scannable at a glance without loud colours.

- Muted accent per kind (`✎` / `⌘` / `☰`) instead of one flat grey; no bright
  or saturated colours, low contrast steps between neighbours.
- Dim the repo prefix (`Mathe_im_Advent ·`), keep the file or command name in
  the normal foreground; the long description after `—` dimmer still.
- Highlight the match and the selected line quietly (soft background, no
  inverted blocks).
- Keep it configurable in `recall.conf`, with a plain no-colour fallback
  (`NO_COLOR`) like the other tools.
