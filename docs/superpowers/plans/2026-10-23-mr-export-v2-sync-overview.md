# mr-export v2, stage 1 (sync + overview) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `mr-export` into a standing local copy of all open MRs — refreshed by a systemd user timer, pruned to the newest 15, reachable at `latest/index.html` — whose overview sorts what matters first, filters by label, shows whether each MR's changes already sit in its target (also when squashed), and shows each MR's diff.

**Architecture:** v1 stays the base (`fetch` → snapshot folder → `render`). A new `gitstate` module reads Git over SSH into the tool's own ref namespace and computes merge state and diffs, stored in the snapshot so pages need no Git. A new `retention` module owns `latest` and pruning; a new `schedule` module writes the systemd units. Rendering gains ordering, filter chips, an age banner computed in the browser, and a diff panel.

**Tech Stack:** Python 3.12 stdlib, `glab api` (GET only), `git` ≥ 2.38 (`merge-tree --write-tree`), systemd user units, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-mr-export-v2-design.md` — Parts A and B, plus the README part of E. Parts C and D get their own plan.

## Global Constraints

- Standard library only; tests run without network and without real `glab`/`systemctl`; real `git` is allowed in tests (temporary repos).
- `fetch` stays GET-only through `Runner.glab_get` and `assert_read_only`; no new code path calls `glab` otherwise.
- Explain-then-run: every external command shown with a one-line explanation before it runs (`Console.step`), repeats shown once; `--quiet` prints only errors.
- A snapshot folder is never written to after its run ended; `render` may rewrite only `index.html` and `mr/*.html`.
- The user's own refs are never touched: Git data goes to `refs/mr-export/heads/<branch>` and `refs/mr-export/mr/<iid>`.
- Defaults: `keep = 15`, `top_labels = ["Approval ready"]`, `emergency_branches = { dev = "notfall/dev", main = "notfall/main" }`.
- Config: global keys, per-repo overrides in `[repo."<clone folder name>"]`; v1 config files stay valid.
- No project data (names, texts, screenshots) from the team in this repository; demo data is invented.
- Code comments timeless (no dates, no "now/before"); commit messages without attribution lines. Commits on the feature branch; the merge to `main` is done by the owner.

## Review Focus

1. API answers but SSH fails (or the reverse) → the run is **partial**, the overview says so, and `latest` keeps pointing at the newest complete snapshot. → Task 4 test `test_latest_prefers_complete_over_older_partial`, Task 3 test `test_git_failure_makes_run_partial`.
2. An MR whose head commit cannot be fetched (deleted source branch, fork) → state `unknown`, no crash, other MRs unaffected. → Task 2 test `test_missing_head_is_unknown`.
3. Huge or binary diffs (lock files, images) → page stays usable: per-file cut with a note, binary files listed without content. → Task 6 tests `test_long_file_diff_is_cut` and `test_binary_file_is_listed_without_lines`.
4. Timer run and a manual run at the same time → the second one stops with a clear message instead of racing; pruning never deletes a folder a running fetch writes. → Task 3 test `test_second_fetch_waits_for_lock_and_stops`.
5. Repo folder name with spaces or umlauts → valid, unique systemd unit names. → Task 8 test `test_unit_name_is_escaped`.

---

### Task 1: Config v2 (new keys, per-repo overrides)

**Files:**
- Modify: `dev/mr-export/src/mr_export/config.py`
- Test: `dev/mr-export/tests/test_config.py` (new)

**Interfaces:**
- Produces: `Config` gains `keep: int = 15`, `top_labels: list[str]`, `emergency_branches: dict[str, str]`, `stale_after_hours: int = 3`; `load_config(path: Path | None = None, repo: str | None = None) -> tuple[Config, Path | None]` — with `repo`, keys from `[repo."<repo>"]` override global ones.

- [ ] **Step 1: Write the failing tests** in `test_config.py`:
  - `test_defaults_without_file` → `keep == 15`, `top_labels == ["Approval ready"]`, `emergency_branches == {"dev": "notfall/dev", "main": "notfall/main"}`, `stale_after_hours == 3`.
  - `test_v1_file_still_loads` → file with only `out_dir`, `state`, `images` loads unchanged.
  - `test_repo_table_overrides_global` → `keep = 10` global, `[repo."Garden Planner"] keep = 5` → `load_config(repo="Garden Planner").keep == 5`, `load_config(repo="other").keep == 10`.
  - `test_wrong_types_name_the_key` → `keep = "x"`, `keep = 0`, `top_labels = "a"`, `emergency_branches = {dev = 1}` each raise `ConfigError` whose message contains the key.
  - `test_unknown_key_in_repo_table_is_an_error` → message names the table and key.
- [ ] **Step 2:** `python3 -m pytest -q dev/mr-export/tests/test_config.py` → FAIL (new fields missing).
- [ ] **Step 3:** Implement. One validator per key, applied to the global level and then to the repo table; `keep` ≥ 1; `stale_after_hours` ≥ 1; `repo` table may hold every key except `repo`.
- [ ] **Step 4:** Whole suite: `python3 -m pytest -q dev/mr-export/tests` → all pass.
- [ ] **Step 5:** Commit `feat(mr-export): config keys for retention, ordering and emergency branches, per-repo tables`.

### Task 2: Git state module

**Files:**
- Create: `dev/mr-export/src/mr_export/gitstate.py`
- Modify: `dev/mr-export/src/mr_export/runner.py` (add `git_ok`)
- Test: `dev/mr-export/tests/test_gitstate.py` (new; builds a bare "origin" and a clone with real `git` under `tmp_path`)

**Interfaces:**
- Produces:
  - `Runner.git_ok(args: list[str], explanation: str | None) -> bool` — exit 0 → True, exit 1 → False, other → `CommandError`.
  - `REF_NS = "refs/mr-export"`
  - `remote_heads(runner: Runner) -> set[str]` — branch names on `origin` (`git ls-remote --heads origin`).
  - `fetch_refs(runner: Runner, branches: list[str]) -> None` — one `git fetch --no-tags origin` with `+refs/heads/<b>:refs/mr-export/heads/<b>` per branch and `+refs/merge-requests/*/head:refs/mr-export/mr/*`; shown once.
  - `merge_state(runner: Runner, head: str, base_ref: str) -> str` — `"yes"` | `"content"` | `"no"` | `"unknown"`.
  - `diff_text(runner: Runner, base_ref: str, head: str) -> str` — `git diff --no-color --no-ext-diff <base>...<head>`.

- [ ] **Step 1: Write the failing tests** (fixture: bare origin with `dev`; clone pushes `feat/a` (2 commits) and sets `refs/merge-requests/1/head` in the bare repo via `git update-ref`):
  - `test_fetch_uses_own_namespace` → after `fetch_refs(r, ["dev"])`: `refs/mr-export/heads/dev` and `refs/mr-export/mr/1` exist; `git for-each-ref refs/remotes` output unchanged.
  - `test_unmerged_branch_is_no` → `merge_state(head_of_feat_a, "refs/mr-export/heads/dev") == "no"`.
  - `test_normal_merge_is_yes` → after `git merge --no-ff feat/a` into dev + push + fetch → `"yes"`.
  - `test_squash_merge_is_content` → after `git merge --squash feat/a` + commit into dev + push + fetch → `"content"`.
  - `test_missing_head_is_unknown` → `merge_state("0"*40, ...) == "unknown"`.
  - `test_diff_shows_only_branch_changes` → `diff_text` contains the branch's file, not a file added to dev after branching.
  - `test_git_ok_maps_exit_codes` → `git_ok(["merge-base","--is-ancestor",a,b])` True/False; unknown object → `CommandError`.
- [ ] **Step 2:** Run `python3 -m pytest -q dev/mr-export/tests/test_gitstate.py` → FAIL (module missing).
- [ ] **Step 3:** Implement. `merge_state`: missing object (`git cat-file -e`) → `unknown`; ancestor (`merge-base --is-ancestor`) → `yes`; else `git merge-tree --write-tree <base> <head>` first line equals `git rev-parse <base>^{tree}` → `content`; else `no`. Any `CommandError` inside → `unknown`.
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): read merge state and diffs from Git into an own ref namespace`.

### Task 3: Fetch v2 (members, Git state, diffs, partial runs, lock, quiet)

**Files:**
- Modify: `dev/mr-export/src/mr_export/fetch.py`, `dev/mr-export/src/mr_export/runner.py` (`Console(quiet=True)`)
- Modify: `dev/mr-export/tests/test_fetch.py`, `dev/mr-export/tests/conftest.py` (fake answers `projects/:id/members/all…`)

**Interfaces:**
- Consumes: Task 2 functions; `Config.emergency_branches`.
- Produces:
  - `fetch(runner, console, root, state, images, now, emergency: dict[str, str], collect=collect_git_state) -> FetchResult`
  - `collect_git_state(runner, console, mrs: list[MergeRequest], emergency: dict[str, str], snap: Path) -> list[str]` — writes `git.json` (`{"<iid>": {"target": state, "emergency": state | null, "emergency_branch": name | null}}`) and `mr/<iid>.diff`; returns failure strings.
  - `members.ndjson` in the snapshot (raw `glab` ndjson of `projects/:id/members/all?per_page=100`, paginated).
  - `meta.json` gains `"partial": bool` (true when `failures` is non-empty).
  - `FetchLocked(Exception)`; lock file `<root>/.fetch.lock` held with `fcntl.flock(LOCK_EX | LOCK_NB)` for the whole run.
  - `Console(err=None, quiet=False)`: with `quiet`, `step`/`result`/`line` print nothing; `note` still prints.

- [ ] **Step 1: Write the failing tests:**
  - `test_members_are_saved` → `members.ndjson` holds the fake's members.
  - `test_git_state_and_diffs_are_written` → with `collect` stub writing `git.json`, `meta["partial"] is False`; the stub received the MRs and `{"dev": "notfall/dev", ...}`.
  - `test_git_failure_makes_run_partial` → stub returns `["git: ssh: connect timed out"]` → `meta["partial"] is True`, `meta["complete"] is True`, the failure is listed.
  - `test_second_fetch_waits_for_lock_and_stops` → holding the lock on `<root>/.fetch.lock` in the test, `fetch(...)` raises `FetchLocked` and creates no folder.
  - `test_quiet_console_prints_only_notes` → `Console(buf, quiet=True)`: `step`/`result` empty, `note` present.
  - Real-Git integration (uses Task 2 fixture): `test_collect_git_state_marks_squashed_mr` → one MR squashed into `dev`, one not → `git.json` `"content"` and `"no"`; `mr/<iid>.diff` exists for both; emergency branch absent on origin → `"emergency": null`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Order inside `fetch`: lock → project → list → MRs/discussions/approvals → members → uploads → `collect` → `write_meta(True)`. `collect_git_state`: `remote_heads`, then `fetch_refs` for all distinct targets plus existing emergency branches; per MR: `merge_state` against `refs/mr-export/heads/<target>`; if that is `no` and the target's emergency branch exists, also against it; diff against the target. Any `CommandError` from the fetch step → one failure `git: <msg>`, no per-MR states (`git.json` not written).
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): fetch members, merge state and diffs; partial runs; one fetch at a time`.

### Task 4: Retention and `latest`

**Files:**
- Create: `dev/mr-export/src/mr_export/retention.py`
- Modify: `dev/mr-export/src/mr_export/cli.py` (call after fetch; `render` without folder uses `latest`)
- Test: `dev/mr-export/tests/test_retention.py` (new)

**Interfaces:**
- Produces:
  - `SNAPSHOT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}_\d{4}(-\d+)?")` — only such folders are ever pruned.
  - `status(path: Path) -> str` — `"complete"` | `"partial"` | `"unfinished"` | `"handmade"` (no `meta.json`).
  - `update_latest(root: Path) -> Path | None` — symlink `root/latest` (relative target) to the newest complete snapshot, or to a partial one newer than it; returns the target.
  - `prune(root: Path, keep: int) -> list[Path]` — returns deleted folders.

- [ ] **Step 1: Write the failing tests** (helper creates folders with `meta.json` of a given status and name):
  - `test_latest_points_to_newest_complete`.
  - `test_latest_prefers_complete_over_older_partial` and `test_latest_takes_newer_partial`.
  - `test_unfinished_never_becomes_latest`.
  - `test_prune_keeps_newest_n` → 20 complete, `keep=15` → 5 oldest deleted.
  - `test_prune_never_deletes_newest_complete` → 1 complete followed by 16 partial, `keep=15` → the complete one survives.
  - `test_prune_drops_old_unfinished_keeps_newest_unfinished`.
  - `test_prune_ignores_foreign_folders` → `2026-10-23_1005-notfall`, `latest`, `notes/` untouched.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; deletion with `shutil.rmtree` only after `SNAPSHOT_NAME.fullmatch` and `status != "handmade"`. In `cmd_fetch`, after render: `update_latest`, `prune(root, cfg.keep)`, both shown as steps (`* Point latest at …`, `* Keep the newest 15 snapshots`) with the deleted names as results. `cmd_render` without folder uses `root/latest`, falling back to v1's `newest_snapshot`.
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): latest link and retention of the newest snapshots`.

### Task 5: Overview — order, filter chips, in-target column, age banner

**Files:**
- Modify: `dev/mr-export/src/mr_export/render.py`, `dev/mr-export/src/mr_export/snapshot.py` (load `git.json` into `MergeRequest.git_state: dict | None`)
- Modify: `dev/mr-export/tests/test_render.py`

**Interfaces:**
- Consumes: `git.json` (Task 3), `Config.top_labels`, `Config.stale_after_hours`.
- Produces: `render(snap: Snapshot, top_labels: list[str] = ["Approval ready"], stale_after_hours: int = 3) -> Path`; `sort_key(mr: MergeRequest, top_labels: list[str]) -> tuple`; each `<tr>` carries `data-labels`, `data-draft`, `data-intarget`, `data-threads`.

- [ ] **Step 1: Write the failing tests:**
  - `test_order_non_drafts_then_top_labels_then_updated` → MRs: draft+"Approval ready", non-draft old, non-draft+"Approval ready", non-draft new → order: non-draft+AR, non-draft new, non-draft old, draft+AR.
  - `test_chip_per_label_with_count` → `>URGENT <span class="count">2</span>` style; chips for "drafts", "in target", "open threads".
  - `test_in_target_column_texts` → states `yes`/`content`/`no`/`unknown` and emergency hit render as `yes`, `yes (squashed)`, `no`, `?`, `in notfall/dev`.
  - `test_age_banner_has_timestamp_and_threshold` → `data-fetched="2026-10-23T10:05:00"` and `data-stale-hours="3"` present; partial run → banner text "Some data could not be read".
  - `test_no_git_json_still_renders` → column shows `?`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `sort_key` = `(draft, not any(top label), -updated_ts)`. Inline JS (no libraries): chips toggle; a row shows when it matches every active chip and the text filter; the banner script computes the age from `data-fetched` and adds class `stale` when older than `data-stale-hours`. CLI passes the config values.
- [ ] **Step 4:** Whole suite passes; render the demo of Task 9 later for a look.
- [ ] **Step 5:** Commit `feat(mr-export): overview sorted by readiness, label filters, merge state, snapshot age`.

### Task 6: MR page — diff panel

**Files:**
- Create: `dev/mr-export/src/mr_export/diffview.py`
- Modify: `dev/mr-export/src/mr_export/render.py` (panel after "Look at the code without GitLab")
- Test: `dev/mr-export/tests/test_diffview.py` (new)

**Interfaces:**
- Produces: `@dataclass FileDiff(path: str, added: int, removed: int, binary: bool, lines: list[str], cut: int)`; `parse(diff: str, max_lines: int = 1500) -> list[FileDiff]`; `render_panel(files: list[FileDiff], git_hint: str) -> str`.

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_counts_per_file` → two files, correct `added`/`removed`.
  - `test_rename_uses_new_path`.
  - `test_long_file_diff_is_cut` → 2000 lines, `max_lines=1500` → `len(lines) == 1500`, `cut == 500`, panel says "500 more lines" and shows the `git diff` hint.
  - `test_binary_file_is_listed_without_lines` → "Binary files … differ" → `binary=True`, panel says "binary".
  - `test_panel_escapes_code` → a line `+<script>` appears as `&lt;script&gt;`.
  - In `test_render.py`: `test_mr_page_has_changes_panel` and `test_mr_page_without_diff_says_so`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Panel: summary list (path, +n −m), then one `<details>` per file with `<pre>` lines classed `add`/`del`/`hunk`; files over 10 changed lines start closed. CSS joins v1's tokens (green/red tints for both themes).
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): diff panel on each MR page`.

### Task 7: `--quiet` and `mr-export open` (Flatpak-aware)

**Files:**
- Modify: `dev/mr-export/src/mr_export/cli.py`
- Create: `dev/mr-export/src/mr_export/browser.py`
- Test: `dev/mr-export/tests/test_browser.py` (new), `dev/mr-export/tests/test_cli.py`

**Interfaces:**
- Produces: `fetch --quiet`; `mr-export open [--repo DIR]`; `browser.flatpak_without_access(runner, path: Path) -> str | None` — returns the Flatpak app id when the default HTML handler is a Flatpak whose `filesystems` permission covers neither `host`, `home` nor a prefix of `path`; `browser.override_command(app_id, path) -> str` → `flatpak override --user --filesystem=<path>:ro <app_id>`.

- [ ] **Step 1: Write the failing tests** (fake runner answering `xdg-mime query default text/html`, `flatpak info <id>`, `flatpak info --show-permissions <id>`):
  - `test_flatpak_without_access_is_detected` → permissions `xdg-download;xdg-documents;` and path under `~/mr-export` → returns `com.google.Chrome`.
  - `test_flatpak_with_home_access_is_fine` → `filesystems=home;` → `None`.
  - `test_regular_browser_is_fine` → `flatpak info` fails → `None`.
  - `test_open_warns_and_still_opens` → stderr has the override command (not run), `xdg-open …/latest/index.html` was called.
  - `test_quiet_fetch_prints_nothing_on_success` (CLI with fake GitLab) → stderr empty, stdout = index path.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `open` uses `Runner` (shown commands) and never runs `flatpak override`.
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): quiet mode and an open command that explains Flatpak browsers`.

### Task 8: `mr-export schedule` (systemd user timer)

**Files:**
- Create: `dev/mr-export/src/mr_export/schedule.py`
- Modify: `dev/mr-export/src/mr_export/cli.py`
- Test: `dev/mr-export/tests/test_schedule.py` (new)

**Interfaces:**
- Produces: `mr-export schedule --every <N>min|<N>h [--repo DIR] | --off | --status`; `unit_name(repo: Path) -> str` (`mr-export-` + `systemd-escape`-compatible slug of the folder name, computed in Python); `unit_files(launcher: Path, repo: Path, every: str) -> dict[str, str]` (file name → content); `parse_every(text: str) -> str` (→ systemd time span, `ValueError` otherwise).

- [ ] **Step 1: Write the failing tests** (`XDG_CONFIG_HOME` in `tmp_path`; fake runner records `systemctl`/`journalctl` calls):
  - `test_unit_files_content` → service `Type=oneshot`, `ExecStart=<launcher> fetch --yes --quiet --repo <repo>` (paths quoted for spaces); timer `OnUnitActiveSec=1h`, `OnBootSec=5min`, `[Install] WantedBy=timers.target`.
  - `test_unit_name_is_escaped` → repo folder `Garden Planner` and `Übung` give distinct names matching `^mr-export-[A-Za-z0-9:_.\\-]+$`.
  - `test_parse_every` → `30min`, `1h`, `2h` ok; `0h`, `5s`, `1d`, `` raise.
  - `test_schedule_shows_files_and_asks` → without `--yes` and no TTY: stops, nothing written; with answer "y": files written under `~/.config/systemd/user/`, then `systemctl --user daemon-reload` and `systemctl --user enable --now <name>.timer` called in this order.
  - `test_schedule_warns_without_ssh_agent` → `systemctl --user show-environment` without `SSH_AUTH_SOCK` → note names `systemctl --user import-environment SSH_AUTH_SOCK`.
  - `test_off_disables_and_removes` and `test_status_shows_timer_and_last_runs` (calls `systemctl --user list-timers <name>.timer --no-pager` and `journalctl --user -u <name>.service -n 20 --no-pager`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; launcher path = the real path of the `mr-export` starter (`Path(sys.argv[0]).resolve()` when it is the starter, else the package's sibling `mr-export`).
- [ ] **Step 4:** Whole suite passes.
- [ ] **Step 5:** Commit `feat(mr-export): schedule fetches with a systemd user timer`.

### Task 9: Demo data, screenshots, docs

**Files:**
- Create: `dev/mr-export/demo/make_demo.py`, `dev/mr-export/docs/img/*.png`
- Modify: `dev/mr-export/README.md`, `dev/mr-export/DESIGN.md`, `dev/mr-export/example.conf`, `.github/workflows/ci.yml` (run `make_demo.py --check` = builds the demo snapshot into a temp dir and renders it)
- Test: `dev/mr-export/tests/test_demo.py`

**Interfaces:**
- Produces: `python3 dev/mr-export/demo/make_demo.py <out_dir> [--screenshots <img_dir>]` — writes an invented snapshot (6 MRs: drafts and non-drafts, labels "Approval ready", "Urgent", "Docs", one squashed-merged, one with a long diff, one with an image, threads with `path:line`), renders it, and with `--screenshots` captures `overview.png` (1400×900), `mr-page.png` (1100×1600) with headless Firefox (`--no-remote --profile <tempdir> --screenshot`).

- [ ] **Step 1:** Test `test_demo_snapshot_renders` → `make_demo.py <tmp>` exits 0, `index.html` lists 6 MRs; every username in the snapshot is one of the invented people (`alice`, `bob`, `carol`, `dan`).
- [ ] **Step 2:** Run → FAIL; implement; run → PASS.
- [ ] **Step 3:** Generate screenshots into `dev/mr-export/docs/img/`; look at both images once.
- [ ] **Step 4:** README: sections Setup (symlink, glab login, first fetch), Keep it current (`schedule`, `--status`, retention, `latest`), Open it (`open`, Flatpak note), What the overview shows (order, chips, in-target meanings, age banner, diff) with the two screenshots, Config (new keys, `[repo."…"]`). DESIGN.md: one entry each for own ref namespace, merge-tree content check, partial vs complete, lock, retention rules, age computed in the browser, Flatpak detection. `example.conf`: new keys with comments.
- [ ] **Step 5:** Commit `docs(mr-export): demo data, screenshots and guide for sync and overview`.

### Task 10: Real-world check and hand-over

- [ ] **Step 1:** Whole suite + `shellcheck dev/mr-export/mr-export` + `bash -n` pass.
- [ ] **Step 2:** In the team's clone: `mr-export fetch` (interactive) against the real GitLab → complete snapshot, `git.json` states plausible: the four MRs labelled "already deployed" show `no` (their changes are not on the server's `dev`).
- [ ] **Step 3:** `mr-export open` → Flatpak warning with override command; open `latest/index.html` in Firefox, click through chips and one MR with diff.
- [ ] **Step 4:** `mr-export schedule --every 1h` interactively (owner confirms), then `mr-export schedule --status` after the first timer run.
- [ ] **Step 5:** Independent review of the branch (fresh reviewer), fix findings with tests; write `.reviews/commit-msg-feat-mr-export-v2.txt` for the merge; the owner merges.
