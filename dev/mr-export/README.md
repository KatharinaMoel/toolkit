# mr-export — GitLab merge requests as a local, offline overview

Read the merge requests of a GitLab project — description, labels, reviewers,
approvals, pipeline status, every comment thread and the images in them — into a
folder on your machine, and get an HTML overview you can open without GitLab.

## The problem

Your team works with merge requests on a self-hosted GitLab. When that server is
down, Git over SSH may still work, but everything that lives only in GitLab's
database is gone for the duration: what each MR is about, who reviews it, which
threads are still open, what the screenshots showed. The code of every MR can be
fetched with Git (`refs/merge-requests/<n>/head`); the conversation around it cannot.

## The idea

- **Read while you can.** `mr-export fetch` stores a snapshot whenever the API
  answers. Run it now and then — before a planned migration, after a review day.
- **Read only, checked.** Every request is a GET through `glab api`. The one place
  that builds `glab` calls refuses any option that could turn a request into a
  write (`-f`, `-F`, `--input`, `--form`, `-X`, `--method`).
- **Nothing is overwritten.** Each run writes a new folder `<date_time>/`; an
  existing snapshot is never touched by `fetch`.
- **Offline pages.** `index.html` lists all MRs with approvals, pipeline and open
  threads, with a filter box; each MR has its own page with description, threads
  (with file and line), system activity, and the `git` commands that show its
  code without GitLab (branch names shell-quoted). Images come from the snapshot; no web fonts, no CDN.
- **Explain-then-run.** Before the first request a header says where it reads from,
  what, and where it writes; then it asks. Every external command is printed with a
  one-line explanation. Calls that repeat per MR are shown once, then one result
  line per MR.

## Requirements

- Python 3.12 (standard library only), Git
- [`glab`](https://gitlab.com/gitlab-org/cli), logged in to your GitLab host
  (`glab auth status`). `mr-export` uses glab's login; it never sees a token.

## Install

```bash
ln -s "$PWD/dev/mr-export/mr-export" ~/.local/bin/mr-export
```

## Use

Run inside a clone whose `origin` is on GitLab (or pass `--repo DIR`):

```bash
mr-export fetch                    # open MRs, with images; asks before it starts
mr-export fetch --state all --yes  # every MR, no question (for scripts)
mr-export render                   # rewrite the pages of the newest snapshot
mr-export render ~/mr-export/app/2026-01-31_0930
```

`fetch` prints the path of `index.html` on stdout; open it with `xdg-open`.
The exit code is 1 when any MR or uploaded file could not be read — the overview
then lists what is missing at the top, and the MR page says so. A read stopped half-way
(Ctrl-C, lost connection) is marked as not finished and skipped by a plain `render`.

Snapshot layout:

```
<out_dir>/<repo>/<YYYY-MM-DD_HHMM>/
  meta.json   mrs.ndjson   index.html
  mr/<iid>.json   mr/<iid>-discussions.ndjson   mr/<iid>-approvals.json   mr/<iid>.html
  uploads/<secret>/<file>
```

`render` also reads a flat folder made by hand with plain `glab api` calls
(`mrs-list.ndjson`, `mr-<iid>.json`, `mr-<iid>-discussions.ndjson`).

## Config

Optional, TOML, at `~/.config/mr-export/mr-export.conf` — see
[`example.conf`](example.conf). Keys: `out_dir` (default `~/mr-export`),
`state` (default `opened`), `images` (default `true`).

## Limits

- A snapshot, not a mirror: what changes on GitLab after the read is not in it.
- Markdown is shown as text with a small subset turned into markup (code blocks,
  inline code, images, links, bold, headings); tables and lists stay plain text.
- Snapshots contain your project's texts and images. Keep `out_dir` outside any
  repository and treat it like the project itself.

## Tests

```bash
python3 -m pytest -q dev/mr-export/tests
```

No network and no real `glab`: a fake answers every call and records it.
