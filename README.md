# toolkit

[![CI](https://github.com/KatharinaMoel/toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/KatharinaMoel/toolkit/actions/workflows/ci.yml)

Personal, opinionated dev & productivity tools — built for my own workflow,
shared in case they're useful. The `ai/` area holds tools that keep work with AI
agents transparent: you see what an agent is told and keep the overview.

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
| [ai/skill-map](ai/skill-map/) | ai | One page of every skill, command, plugin and agent Claude Code can use — where it lives, how often it is used, its full text unchanged — with a session start reminder when the page is out of date |
| [ai/skill-show](ai/skill-show/) | ai | Shows the file behind a Claude Code skill or slash command byte for byte, with its path and the precedence among same-named ones — no model reads it for you |
| [dev/wt](dev/wt/) | dev | Disposable git worktrees for parallel MR reviews and branch work — with per-review database copies |
| [dev/mr-export](dev/mr-export/) | dev | GitLab merge requests — descriptions, threads, approvals, pipeline, images — read-only into a local snapshot with an offline HTML overview, for when the server is down |
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
- **Private patterns:** strings that must never reach this public repository (your
  home folder, private project names) go one per line into
  `~/.config/toolkit/private-patterns` (or the file `TOOLKIT_PRIVATE_PATTERNS`
  names); a staged file containing one stops the commit with file and line. The
  file stays local, so the patterns themselves are never published. Without it the
  check is skipped.
- **Shell checks:** `bash -n` and `shellcheck` on the staged versions of the scripts
  that CI checks; keep the list in the hook in sync with `ci.yml`. ShellCheck runs in
  CI's version (0.9.0, `docker.io/koalaman/shellcheck:v0.9.0`) through podman or
  docker when one is installed, because a newer local ShellCheck misses findings
  that turn CI red. Without a container runtime, or when the image cannot be pulled,
  the hook falls back to the local `shellcheck`; `TOOLKIT_SHELLCHECK_IMAGE=` (empty)
  forces that, another value picks a different image.
- **Bypass once:** `git commit --no-verify`.

## License

[MIT](LICENSE)
