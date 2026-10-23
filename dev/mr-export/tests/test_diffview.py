from mr_export.diffview import parse, render_panel

TWO_FILES = """diff --git a/app/views.py b/app/views.py
index 1111111..2222222 100644
--- a/app/views.py
+++ b/app/views.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = 3
 print(x)
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def test_parse_counts_per_file():
    files = parse(TWO_FILES)
    assert [(f.path, f.added, f.removed) for f in files] == [("app/views.py", 2, 1), ("README.md", 1, 1)]


def test_rename_uses_new_path():
    diff = ("diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n"
            "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-a\n+b\n")
    assert parse(diff)[0].path == "new.py"


def test_new_and_deleted_files():
    diff = ("diff --git a/n.txt b/n.txt\nnew file mode 100644\n--- /dev/null\n+++ b/n.txt\n@@ -0,0 +1 @@\n+hi\n"
            "diff --git a/d.txt b/d.txt\ndeleted file mode 100644\n--- a/d.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n")
    assert [(f.path, f.added, f.removed) for f in parse(diff)] == [("n.txt", 1, 0), ("d.txt", 0, 1)]


def test_long_file_diff_is_cut():
    body = "".join(f"+line {i}\n" for i in range(2000))
    diff = f"diff --git a/big.txt b/big.txt\n--- a/big.txt\n+++ b/big.txt\n@@ -0,0 +1,2000 @@\n{body}"
    f = parse(diff, max_lines=1500)[0]
    assert len(f.lines) == 1500 and f.cut == 501 and f.added == 2000   # hunk header + 2000 lines
    html = render_panel([f], "git diff origin/dev...origin/mr/1")
    assert "501 more lines" in html and "git diff origin/dev...origin/mr/1" in html


def test_binary_file_is_listed_without_lines():
    diff = "diff --git a/logo.png b/logo.png\nindex 1..2 100644\nBinary files a/logo.png and b/logo.png differ\n"
    f = parse(diff)[0]
    assert f.binary and f.path == "logo.png" and f.lines == []
    assert "binary" in render_panel([f], "")


def test_panel_escapes_code():
    diff = "diff --git a/x.html b/x.html\n--- a/x.html\n+++ b/x.html\n@@ -0,0 +1 @@\n+<script>alert(1)</script>\n"
    html = render_panel(parse(diff), "")
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_panel_classes_and_summary():
    html = render_panel(parse(TWO_FILES), "")
    assert '<span class="add">+x = 2</span>' in html and '<span class="del">-x = 1</span>' in html
    assert '<span class="hunk">@@ -1,3 +1,4 @@</span>' in html
    assert "2 files" in html and "+3" in html and "−2" in html


def test_empty_diff():
    assert "No changes" in render_panel(parse(""), "")


def test_diff_lines_have_no_blank_line_between_them():
    html = render_panel(parse(TWO_FILES), "")
    assert '</span>\n<span' not in html   # spans are blocks; a newline would add an empty line


def test_total_budget_lists_remaining_files_only():
    diff = "".join(f"diff --git a/f{i}.txt b/f{i}.txt\n--- a/f{i}.txt\n+++ b/f{i}.txt\n@@ -0,0 +1,100 @@\n"
                   + "".join(f"+x{j}\n" for j in range(100)) for i in range(100))
    files = parse(diff, max_lines=1500, max_total=1000)
    shown = sum(len(f.lines) for f in files)
    assert shown <= 1000 and len(files) == 100 and files[-1].added == 100
    html = render_panel(files, "git diff a...b")
    assert "f99.txt" in html and "not shown" in html


def test_very_long_line_is_shortened():
    line = "+" + "a" * 20000
    diff = f"diff --git a/min.js b/min.js\n--- a/min.js\n+++ b/min.js\n@@ -0,0 +1 @@\n{line}\n"
    f = parse(diff)[0]
    assert len(f.lines[1]) < 2100 and f.lines[1].endswith("…")
