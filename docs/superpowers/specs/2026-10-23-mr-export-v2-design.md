# mr-export v2 — design

Status: draft for approval · Tool: `dev/mr-export/` (v1 is merged: `fetch`, `render`)

## Intent and why

A small team works with GitLab merge requests (MRs). Its self-hosted GitLab goes
down now and then — overload, DDoS, a two-day security shutdown. During the
last outage Git over SSH still worked, but two things were lost:

1. **The overview.** In a busy phase there are 50+ open MRs. What each one is
   about, which are ready, who must approve — all of that lives in GitLab's
   MR descriptions and comments, which are unreachable when the web/API is down.
2. **The safety net.** People merged branches locally and deployed from their
   laptops. No review, no approval, and merges that never reached the server
   (the MRs still show as open; labels like "already deployed" were set by hand).

v2 makes the tool a **standing local copy** of the MR state (refreshed on a
timer) and adds a **Git-only fallback for the MR workflow** — open, review,
approve, merge — that works over SSH alone and hands everything back to GitLab
when it returns.

The person commissioning this uses it first on their own machine; the team may
adopt it later. Everything must work for one person and extend to the team
without redesign.

## Goals

- A local copy of all open MRs is never older than one sync interval while
  GitLab answers, and is readable offline at a stable path.
- The overview answers in seconds: what is ready to merge, what needs review,
  what changed, and — from Git, not from labels — whether an MR's head commit
  already sits in its target branch on the server.
- Each MR page shows the code diff, so a review is possible without GitLab.
- During an outage, a second person can review and approve an MR, and only a
  maintainer can merge it, into an emergency branch, over SSH.
- When GitLab is back, local MRs, review comments and approvals can be carried
  over, each write shown and confirmed.
- Two guides: the public tool README with screenshots from invented demo data,
  and an internal German team guide for the commissioning team.

## Non-goals

- Replacing GitLab or mirroring it two-way. Offline edits to *GitLab* MRs
  (their descriptions, their threads) are not synced back.
- Notifications. Pings stay in the team's chat/task tool.
- Enforcing permissions. Local checks prevent mistakes; the server's branch
  protection is the real boundary (see "Operational prerequisite").
- Pipelines. Tests run locally; deployment stays manual during an outage.

## Anti-goals (would make this a failure even if it works)

- Any write to GitLab, or push to a shared branch, that the user did not see
  and confirm. No `--yes` for writes; no writes from the timer.
- A local flow that makes it *easier* to skip the second pair of eyes than
  today's "merge locally and deploy".
- Losing a snapshot or local review data through the tool's own cleanup or an
  interrupted run.
- Real project data (texts, names, screenshots) in this public repository.

## Constraints

- Python 3.12 standard library only, Bash launcher, `glab` for the API, `git`
  for everything else — same as v1. Tests without network, in CI.
- Explain-then-run as in v1: header + question before the first access; every
  external command shown with a one-line explanation; repeats shown once.
- v1 promises hold: fetch is GET-only (guarded), never writes into an existing
  snapshot, escapes all GitLab text, pages work offline without CDN/fonts.
- The tool never changes the user's checked-out branch or working tree.
- Config (TOML, `~/.config/mr-export/mr-export.conf`) holds everything
  personal; the repo holds nothing project-specific. *Builder's call:* global
  keys at the top, per-repo overrides in `[repo."<repo name>"]` tables (repo
  name = folder name of the clone), settled now so team use needs no format
  change. v1 files stay valid.

## Operational prerequisite (team, not code)

Create **two** emergency branches on the server **now**, `notfall/dev` (from
`dev`) and `notfall/main` (from `main`), each protected with "push:
Maintainers". The team needs both: work for staging and fixes for production.
Then during an outage only a maintainer can push there, whatever anyone sets
locally. `dev` and `main` stay on "push: No one". When GitLab is back, each
emergency branch goes to its base as one MR. Names are configurable as a
mapping (`emergency_branches = { dev = "notfall/dev", main = "notfall/main" }`).
The README and team guide state this; the tool checks for the branches and
warns if one is missing.

Note: CI deploys only from `dev` and `main`, so merging into an emergency
branch deploys nothing. Deployment during an outage stays a manual step.

---

## Part A — Sync on a timer, with retention

Decided:

- `mr-export fetch` stays the one way to read. New: it also reads
  - project members with their role (`projects/:id/members/all`) →
    `members.json` (used for the maintainer check in Part C);
  - over SSH, the target branches of all MRs and every MR head
    (`refs/merge-requests/*/head`), into the tool's **own ref namespace**
    `refs/mr-export/…` — never into the user's `refs/remotes/`;
  - for each MR: whether its changes already sit in its target branch or in
    its emergency branch on the server ("in target: yes / yes (squashed) /
    no"). *Builder's call:* "yes" when the head commit is an ancestor;
    "yes (squashed)" when every commit's patch is already there (`git cherry`
    reports none missing) or a `Local-MR:` trailer for this branch is found —
    the team squashes, so ancestry alone would miss exactly the cases this
    column exists for;
  - the diff
    `git diff <target>...<head>` stored as `mr/<iid>.diff` so pages need no
    Git at view time.
- **Retention: keep the 15 newest complete snapshots** (`keep = 15` in config).
  Pruning runs at the end of a successful fetch and only deletes complete
  snapshots older than the 15th. Unfinished ones older than the newest
  complete one are deleted too; the newest unfinished one is kept for
  inspection.
- *Builder's call:* a run is **complete** only when every read succeeded (API
  and SSH). A run that finished with gaps is **partial** (`partial: true` in
  `meta.json`, exit 1): it becomes `latest` only if it is newer than the
  newest complete one, and pruning never deletes the newest complete
  snapshot, whatever follows it.
- **Stable entry point:** a `latest` symlink in `<out_dir>/<repo>/` points at
  the newest complete snapshot, so `…/latest/index.html` can be bookmarked.
- **Timer:** `mr-export schedule --every 1h` (also `--off`, `--status`) writes
  a systemd **user** service + timer for the current repo, shows both files
  and the `systemctl --user` commands before running them, and asks. The
  service runs `mr-export fetch --yes --quiet --repo <path>`. `--quiet`
  prints only errors (for the journal); no prompts.
- *Builder's call:* the timer runs only while the user is logged in (no
  lingering), so `glab`'s keyring and the session's SSH agent are available;
  `schedule` checks that `SSH_AUTH_SOCK` is visible to the user manager and
  says how to fix it if not. `schedule --status` shows the last run's result
  from the journal, so silent hourly failures surface.
- When GitLab does not answer, the run ends without a new folder and with a
  non-zero exit; the last complete snapshot stays `latest`.
- **Browser:** `mr-export open` opens `latest/index.html`. If the default
  browser for HTML is a Flatpak without access to `out_dir`, it says so and
  shows the `flatpak override --user --filesystem=<out_dir>:ro <app>` command
  (not run) — Flatpak browsers otherwise see only the one file, and every link
  from the overview breaks.

## Part B — Overview

Decided:

- **Order:** non-drafts before drafts; within each, MRs carrying any label in
  `top_labels` (config, default `["Approval ready"]`) first; then newest
  `updated_at` first.
- **Filters** above the table: one chip per label present (with count), plus
  "drafts", "in target", "has open threads". Chips combine; the text filter
  stays. Labels change often, so they filter, they do not sort.
- **Columns:** add "in target" (yes/no from Part A) next to pipeline.
- **Snapshot age** at the top ("read 2 h ago"), red when older than
  `3 × interval` or when the newest run was unfinished.
- **MR page:** a "Changes" panel with the diff: file list with +/- counts, one
  collapsible block per file (`<details>`), added/removed lines colored. Very
  large diffs are cut per file with a note and the `git diff` command to see
  the rest. No syntax highlighting.
- **Local MRs** (Part C) appear in the same table, marked "local", with their
  own pages built the same way.
- *Builder's call:* snapshots stay immutable. `local sync` renders an
  **outage view** into `<out_dir>/<repo>/outage/` (rewritten on each sync):
  the GitLab MRs of `latest` plus local requests and reviews, with local
  diffs computed at sync time and stored there. One row per source branch:
  a branch with both a GitLab MR and local reviews shows once, with the
  local reviews added to that MR's page.

## Part C — Local MRs over Git (the outage workflow)

Decided:

- **Storage:** a branch `mr-local` on the same remote, holding only text files,
  never code:
  ```
  requests/<source-branch-slug>.md           front matter + description
  reviews/<source-branch-slug>/<username>.md  comments + optional approval
  ```
  Request front matter: `title`, `source`, `target`, `author`, `labels`,
  `created`, `status` (open / merged / closed), `gitlab_iid` (after Part D).
  Review front matter: `reviewer`, `approved_sha` (empty = comment only),
  `created`. Body is Markdown; comments may cite `path:line`.
- One file per person per review, so two people never edit the same file.
- The tool writes to `mr-local` **without a checkout** (plumbing: a temporary
  index, `commit-tree`, `update-ref`), then pushes; on a rejected push it
  fetches, re-applies its single-file change, and retries once, then stops
  with an explanation.
- **Commands** (all under `mr-export local`):
  - `open <branch> [--target notfall/dev|notfall/main]` (default: the emergency
    branch of the GitLab MR's target, else `notfall/dev`) — checks the branch is pushed,
    opens `$EDITOR` with a template, commits + pushes the request file.
    *Builder's call:* if the branch already has a GitLab MR in `latest`, no
    new request is needed — `review` and `merge` work on it directly, and a
    request file, if made, carries its `gitlab_iid` from the start. In an
    outage most work under review is already a GitLab MR.
  - `list` — local MRs with state, approvals, "approval valid for current head".
  - `review <branch> [--approve]` — opens `$EDITOR` for comments; `--approve`
    records the branch's current head SHA. Refused for the request's author.
  - `merge <branch>` — see rules below.
  - `sync` — fetch `mr-local`, code branches, and re-render the overview.
- **Identity:** the GitLab username from config (`username = "…"`), else from
  `glab`'s stored login. Shown in every header. Stated plainly in docs: this
  prevents mistakes, it is not a security boundary.
- **Merge rules** (`local merge`), all checked before anything changes:
  1. the current user is Maintainer or Owner in the last `members.json`;
  2. there is an approval by someone other than the author;
  3. that approval's `approved_sha` equals the branch's current head on the
     remote (new commits invalidate it, as in GitLab);
  4. the target is an emergency branch from `emergency_branches`, never `dev`
     or `main` themselves;
  5. **the emergency branch is current:** it contains the server's current
     base branch (`dev` for `notfall/dev`, `main` for `notfall/main`). If it
     only lags behind, the tool offers to fast-forward it to the base (a
     push only maintainers can make), shown and confirmed. If it has
     diverged (own commits and missing base commits), it refuses and
     explains — otherwise a merge would quietly carry unreviewed base
     commits into the emergency branch.
  Then: show the plan, ask, squash-merge in a temporary worktree (the user's
  checkout stays untouched), commit message with trailers
  `Local-MR: <slug>`, `Author:`, `Approved-by:`, `Approved-SHA:`, push the
  emergency branch, mark the request `merged`, push `mr-local`.
  Squash is the default because the team squashes MRs into `dev`; `--no-squash`
  exists.

## Part D — Hand back to GitLab

Decided:

- `mr-export local publish` lists what GitLab does not have yet and walks
  through it, **one confirmed write at a time**, via `glab`:
  - open local MRs without `gitlab_iid` → `glab mr create` with title,
    description, source, target (the target is rewritten from the emergency
    branch to `dev` only if the user confirms);
  - review comments → one MR note per review file, prefixed with reviewer and
    date ("Review given offline on …");
  - reviews of local MRs already merged into the emergency branch → notes on
    the matching `notfall/… → dev|main` MR, one per local MR, so the offline review trail
    reaches GitLab (*builder's call*);
  - reviews on branches that already had a GitLab MR → notes on that MR;
  - approvals: only the **current user's own** approvals, via
    `glab mr approve`, and only if the approved SHA is still the head. Others
    are listed as "ask <name> to approve".
  - each emergency branch with new commits → offer `glab mr create` to its
    base (`notfall/dev → dev`, `notfall/main → main`).
- Results (`gitlab_iid`, "published" marks) are written back to `mr-local` so
  nothing is sent twice.
- Writes go through a separate write runner; the v1 read-only guard stays in
  force for `fetch`. No `--yes`, no run without a terminal.

## Part E — Documentation

Decided:

- **Tool README** (English, public): setup, timer, daily use, outage workflow,
  hand-back, Flatpak note, limits — with screenshots of the overview, an MR
  page with diff, `local list`, and a merge refusal. Screenshots come from an
  **invented demo snapshot** generated by a script in the repo
  (`dev/mr-export/demo/`), rendered and captured with headless Firefox; the
  script is kept so screenshots can be regenerated.
- **Team guide** (German, internal, for the commissioning team): the same
  flows with the team's real paths and branch names, plus the operational
  prerequisite and the agreed rules (who merges, emergency branches). It lives
  in the team's own repository under `docs/`, on a **local branch that is not
  pushed** until the commissioning person decides to share it; sharing is
  then a push plus an MR, nothing to rewrite. Its screenshots may show real
  data only because that repository is private.
- `DESIGN.md` gets an entry per decision above.

## Who uses it, and when

For now one person uses it, on their own machine, as a fallback in case the
planned move to gitlab.com does not end the outages soon. The team may adopt
it later; nothing may assume a single user. Parts A and B are useful alone.
Parts C and D only become usable once at least one more person takes part
(a review needs a second person) — they are built, tested and documented, but
their real use waits for that agreement.

## Delivery order

1. A + B (sync, retention, timer, overview with diff and order) — useful alone.
2. E's README part for A + B.
3. C (local MRs) and D (hand-back) — need team agreement before real use.
4. E complete, team guide last.

## Left to the builder

- Module layout, names of internal functions, test structure.
- Exact HTML/CSS of chips, diff blocks and the age banner, within v1's style.
- Diff cut-off size; the slug rule for branch names in file paths.
- systemd unit details (naming per repo, `Persistent=true` or not, jitter).
- How unfinished snapshots are recognised for pruning beyond `meta.json`.
