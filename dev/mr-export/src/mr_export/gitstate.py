"""What Git over SSH says about merge requests: is their change already in the target
branch, and what is the diff. Everything is fetched into the tool's own ref namespace,
so the user's branches and remote-tracking refs stay untouched."""
from .runner import CommandError, Runner

REMOTE = "origin"
REF_NS = "refs/mr-export"


def head_ref(branch: str) -> str:
    return f"{REF_NS}/heads/{branch}"


def mr_ref(iid: int) -> str:
    return f"{REF_NS}/mr/{iid}"


def remote_heads(runner: Runner) -> set[str]:
    out = runner.git(["ls-remote", "--heads", REMOTE], "List the branches on the server (over SSH)")
    return {line.split("refs/heads/", 1)[1] for line in out.splitlines() if "refs/heads/" in line}


def fetch_refs(runner: Runner, branches: list[str]) -> None:
    specs = [f"+refs/heads/{b}:{head_ref(b)}" for b in sorted(set(branches))]
    specs.append(f"+refs/merge-requests/*/head:{REF_NS}/mr/*")
    runner.git(["fetch", "--no-tags", "--quiet", REMOTE, *specs],
               f"Fetch the target branches and every MR's commits into {REF_NS}/ (not into your branches)")


def merge_state(runner: Runner, head: str, base_ref: str) -> str:
    """'yes' (head is part of base), 'content' (base already holds the same changes,
    e.g. squashed or cherry-picked), 'no', 'conflict' (merging would conflict - either not
    merged, or merged and changed again since), or 'unknown' (head or base not available)."""
    try:
        if not runner.git_ok(["cat-file", "-e", f"{head}^{{commit}}"], None):
            return "unknown"
        if runner.git_ok(["merge-base", "--is-ancestor", head, base_ref], None):
            return "yes"
        # Merging head into base changes nothing -> its changes are already there.
        # Exit 1 means conflicts. (--quiet is not used: it can report success although
        # there are conflicts.) Writes only loose objects into .git, no refs.
        code, out = runner.git_status(["merge-tree", "--write-tree", base_ref, head], None)
        if code == 1:
            return "conflict"
        merged = out.splitlines()[0]
        base_tree = runner.git(["rev-parse", f"{base_ref}^{{tree}}"], None)
        return "content" if merged == base_tree else "no"
    except (CommandError, IndexError):
        return "unknown"


def diff_text(runner: Runner, base_ref: str, head: str) -> str:
    return runner.git(["diff", "--no-color", "--no-ext-diff", f"{base_ref}...{head}"], None)
