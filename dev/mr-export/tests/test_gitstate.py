"""Real git in throwaway repositories: a bare 'origin' and a clone that pushes to it."""
import subprocess
from io import StringIO

import pytest

from mr_export import gitstate
from mr_export.runner import CommandError, Console, Runner


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo, name, text):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """origin (bare) with dev; clone with feat/a (2 commits) pushed; MR 1 points at feat/a."""
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "tester",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "tester",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git(clone, "checkout", "-q", "-b", "dev")
    commit(clone, "base.txt", "base\n")
    git(clone, "push", "-q", "origin", "dev")
    git(clone, "checkout", "-q", "-b", "feat/a")
    commit(clone, "a1.txt", "one\n")
    head = commit(clone, "a2.txt", "two\n")
    git(clone, "push", "-q", "origin", "feat/a")
    git(origin, "update-ref", "refs/merge-requests/1/head", head)
    git(clone, "checkout", "-q", "dev")
    runner = Runner(clone, Console(StringIO()))
    return origin, clone, runner, head


def test_fetch_uses_own_namespace(repos):
    _, clone, runner, head = repos
    before = git(clone, "for-each-ref", "refs/remotes")
    gitstate.fetch_refs(runner, ["dev"])
    assert git(clone, "rev-parse", "refs/mr-export/mr/1") == head
    assert git(clone, "rev-parse", "refs/mr-export/heads/dev")
    assert git(clone, "for-each-ref", "refs/remotes") == before


def test_remote_heads_lists_branches(repos):
    _, _, runner, _ = repos
    assert gitstate.remote_heads(runner) == {"dev", "feat/a"}


def test_unmerged_branch_is_no(repos):
    _, _, runner, head = repos
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, head, "refs/mr-export/heads/dev") == "no"


def test_normal_merge_is_yes(repos):
    _, clone, runner, head = repos
    git(clone, "merge", "-q", "--no-ff", "-m", "merge", "feat/a")
    git(clone, "push", "-q", "origin", "dev")
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, head, "refs/mr-export/heads/dev") == "yes"


def test_squash_merge_is_content(repos):
    _, clone, runner, head = repos
    git(clone, "merge", "-q", "--squash", "feat/a")
    git(clone, "commit", "-q", "-m", "squashed feat/a")
    git(clone, "push", "-q", "origin", "dev")
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, head, "refs/mr-export/heads/dev") == "content"


def test_missing_head_is_unknown(repos):
    _, _, runner, _ = repos
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, "0" * 40, "refs/mr-export/heads/dev") == "unknown"


def test_diff_shows_only_branch_changes(repos):
    _, clone, runner, head = repos
    commit(clone, "later-on-dev.txt", "x\n")
    git(clone, "push", "-q", "origin", "dev")
    gitstate.fetch_refs(runner, ["dev"])
    diff = gitstate.diff_text(runner, "refs/mr-export/heads/dev", head)
    assert "a1.txt" in diff and "a2.txt" in diff
    assert "later-on-dev.txt" not in diff


def test_git_ok_maps_exit_codes(repos):
    _, clone, runner, head = repos
    base = git(clone, "rev-parse", "dev")
    assert runner.git_ok(["merge-base", "--is-ancestor", base, head], None) is True
    assert runner.git_ok(["merge-base", "--is-ancestor", head, base], None) is False
    with pytest.raises(CommandError):
        runner.git_ok(["merge-base", "--is-ancestor", "nope", base], None)


@pytest.mark.real_git
def test_collect_git_state_marks_squashed_mr(repos, tmp_path):
    import json
    from mr_export.fetch import collect_git_state
    from mr_export.snapshot import MergeRequest
    origin, clone, runner, head_a = repos
    git(clone, "checkout", "-q", "-b", "feat/b", "dev")
    head_b = commit(clone, "b.txt", "b\n")
    git(clone, "push", "-q", "origin", "feat/b")
    git(origin, "update-ref", "refs/merge-requests/2/head", head_b)
    git(clone, "checkout", "-q", "dev")
    git(clone, "merge", "-q", "--squash", "feat/a")
    git(clone, "commit", "-q", "-m", "squashed feat/a")
    git(clone, "push", "-q", "origin", "dev")
    mrs = [MergeRequest(data={"iid": 1, "sha": head_a, "target_branch": "dev"}),
           MergeRequest(data={"iid": 2, "sha": head_b, "target_branch": "dev"})]
    snap = tmp_path / "snap"
    (snap / "mr").mkdir(parents=True)
    failures = collect_git_state(runner, Console(StringIO()), mrs, {"dev": "notfall/dev"}, snap)
    assert failures == []
    state = json.loads((snap / "git.json").read_text())
    assert state["1"] == {"target": "content", "emergency": None, "emergency_branch": None}
    assert state["2"]["target"] == "no"
    assert "a1.txt" in (snap / "mr" / "1.diff").read_text()
    assert "b.txt" in (snap / "mr" / "2.diff").read_text()


@pytest.mark.real_git
def test_collect_checks_existing_emergency_branch(repos, tmp_path):
    import json
    from mr_export.fetch import collect_git_state
    from mr_export.snapshot import MergeRequest
    _, clone, runner, head_a = repos
    git(clone, "checkout", "-q", "-b", "notfall/dev", "dev")
    git(clone, "merge", "-q", "--no-ff", "-m", "emergency merge", "feat/a")
    git(clone, "push", "-q", "origin", "notfall/dev")
    snap = tmp_path / "snap"
    (snap / "mr").mkdir(parents=True)
    collect_git_state(runner, Console(StringIO()),
                      [MergeRequest(data={"iid": 1, "sha": head_a, "target_branch": "dev"})],
                      {"dev": "notfall/dev"}, snap)
    state = json.loads((snap / "git.json").read_text())
    assert state["1"] == {"target": "no", "emergency": "yes", "emergency_branch": "notfall/dev"}


@pytest.mark.real_git
def test_collect_reports_unreachable_remote(repos, tmp_path):
    from mr_export.fetch import collect_git_state
    from mr_export.snapshot import MergeRequest
    _, clone, runner, head_a = repos
    git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    snap = tmp_path / "snap"
    (snap / "mr").mkdir(parents=True)
    failures = collect_git_state(runner, Console(StringIO()),
                                 [MergeRequest(data={"iid": 1, "sha": head_a, "target_branch": "dev"})],
                                 {"dev": "notfall/dev"}, snap)
    assert len(failures) == 1 and failures[0].startswith("git: ")
    assert not (snap / "git.json").exists()


def test_conflicting_branch_is_unclear_not_unknown(repos):
    """git merge-tree exits 1 on conflicts; a conflict means the change is not in the target."""
    _, clone, runner, _ = repos
    git(clone, "checkout", "-q", "-b", "feat/c", "dev")
    head_c = commit(clone, "base.txt", "branch version\n")
    git(clone, "push", "-q", "origin", "feat/c")
    git(clone, "checkout", "-q", "dev")
    commit(clone, "base.txt", "dev version\n")
    git(clone, "push", "-q", "origin", "dev")
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, head_c, "refs/mr-export/heads/dev") == "conflict"


def test_diff_of_non_utf8_file_does_not_crash(repos):
    _, clone, runner, _ = repos
    git(clone, "checkout", "-q", "-b", "feat/latin1", "dev")
    (clone / "names.csv").write_bytes("Müller;Straße\n".encode("latin-1"))
    git(clone, "add", "names.csv")
    git(clone, "commit", "-q", "-m", "latin-1 file")
    head = git(clone, "rev-parse", "HEAD")
    git(clone, "push", "-q", "origin", "feat/latin1")
    gitstate.fetch_refs(runner, ["dev"])
    diff = gitstate.diff_text(runner, "refs/mr-export/heads/dev", head)
    assert "names.csv" in diff and "M�ller" in diff


def test_conflict_is_reported_as_unclear_not_no(repos):
    """A conflict proves nothing: a squashed change edited again on dev also conflicts."""
    _, clone, runner, _ = repos
    git(clone, "checkout", "-q", "-b", "feat/c", "dev")
    head_c = commit(clone, "base.txt", "Y\n")
    git(clone, "push", "-q", "origin", "feat/c")
    git(clone, "checkout", "-q", "dev")
    git(clone, "merge", "-q", "--squash", "feat/c")
    git(clone, "commit", "-q", "-m", "squash feat/c")
    commit(clone, "base.txt", "Z\n")          # the same line changed again after the squash
    git(clone, "push", "-q", "origin", "dev")
    gitstate.fetch_refs(runner, ["dev"])
    assert gitstate.merge_state(runner, head_c, "refs/mr-export/heads/dev") == "conflict"


@pytest.mark.real_git
def test_unfetchable_head_is_not_a_failure(repos, tmp_path):
    import json
    from mr_export.fetch import collect_git_state
    from mr_export.snapshot import MergeRequest
    _, _, runner, _ = repos
    snap = tmp_path / "snap"
    (snap / "mr").mkdir(parents=True)
    failures = collect_git_state(runner, Console(StringIO()),
                                 [MergeRequest(data={"iid": 7, "sha": "f" * 40, "target_branch": "dev"})],
                                 {}, snap)
    assert failures == []
    assert json.loads((snap / "git.json").read_text())["7"]["target"] == "unknown"
    assert not (snap / "mr" / "7.diff").exists()
