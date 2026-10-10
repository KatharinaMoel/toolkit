# toolkit

[![CI](https://github.com/KatharinaMoel/toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/KatharinaMoel/toolkit/actions/workflows/ci.yml)

Personal, opinionated dev & productivity tools — built for my own workflow,
shared in case they're useful.

Built and tested on **Fedora Linux**; most tools are plain Bash and should run
on any Linux. Each tool's README states its actual requirements.

## Principles

- **Explain-then-run**: every command a tool executes is printed first, with a
  one-line explanation. No black boxes — running a tool teaches you the steps.
- **Engine/config split**: tools are generic; project- or machine-specific
  values live in local config files (`~/.config/<tool>/…`) that never enter
  this repository. Each tool ships an anonymized `example.conf` instead.
- **Fail fast, stay transparent**: `set -euo pipefail`, no silent fallbacks.

## Tools

| Tool | Area | What it does |
|------|------|--------------|
| [dev/wt](dev/wt/) | dev | Disposable git worktrees for parallel MR reviews and branch work — with per-review database copies |
| [dev/recall](dev/recall/) | dev | One hotkey, one fuzzy list: copy prepared commit/MR texts and forgotten commands, read procedures — with Claude Code as a read-only fallback for fuzzy questions |
| [media/transcribe](media/transcribe/) | media | Public podcast episodes (or any audio) to Markdown — the publisher's transcript when the feed has one, otherwise local CPU recognition with timestamps; resumable queue for multi-day runs |

## Development

CI (`.github/workflows/ci.yml`) is the binding check: `bash -n`, ShellCheck and the
tests. An optional local `pre-commit` hook in [`.githooks/`](.githooks/) gives the
same early warning before a commit, plus a secret scan of the staged content:

```bash
git config core.hooksPath .githooks   # once per clone; worktrees share it
```

- **Opt-in:** git does not clone hook settings, so a fresh `git clone` has no hook
  until you run the command above. Branches created before `.githooks/` existed
  are not covered either.
- **Secret scan:** uses the author's own scanner `kios` (not published). If it is
  not found (set `KIOS_BIN` to point to it), the hook stops the commit instead of
  skipping the scan silently. Without `kios`, leave the hook off or replace the scan
  step in `.githooks/pre-commit` with your own scanner.
- **Shell checks:** `bash -n` and `shellcheck` on the staged versions of the scripts
  that CI checks; keep the list in the hook in sync with `ci.yml`.
- **Bypass once:** `git commit --no-verify`.

## License

[MIT](LICENSE)
