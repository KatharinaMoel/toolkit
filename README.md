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
| [media/transcribe](media/transcribe/) | media | Public podcast episodes (or any audio) to Markdown — the publisher's transcript when the feed has one, otherwise local CPU recognition with timestamps; resumable queue for multi-day runs |

## License

[MIT](LICENSE)
