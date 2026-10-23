"""A unified diff (as `git diff` prints it) turned into a panel for the MR page:
a summary, then one collapsible block per file. Very long files are cut."""
import html
import re
from dataclasses import dataclass, field


@dataclass
class FileDiff:
    path: str
    added: int = 0
    removed: int = 0
    binary: bool = False
    lines: list[str] = field(default_factory=list)   # hunk headers and changed/context lines
    cut: int = 0                                      # lines left out after max_lines


MAX_LINE = 2000   # characters; minified files would otherwise make one endless line


def parse(diff: str, max_lines: int = 1500, max_total: int = 6000) -> list[FileDiff]:
    """Per file at most `max_lines` lines, per page at most `max_total`; beyond that a
    file keeps only its counts and is listed, not shown."""
    files: list[FileDiff] = []
    total = 0
    cur: FileDiff | None = None
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = FileDiff(path=m.group(2) if m else line[11:])
            files.append(cur)
            in_hunk = False
            continue
        if cur is None:
            continue
        if not in_hunk:
            if line.startswith("rename to "):
                cur.path = line[len("rename to "):]
            elif line.startswith("Binary files "):
                cur.binary = True
            elif line.startswith("+++ ") and line[4:] != "/dev/null":
                cur.path = line[6:] if line.startswith("+++ b/") else cur.path
            if not line.startswith("@@"):
                continue
            in_hunk = True
        if line.startswith("+"):
            cur.added += 1
        elif line.startswith("-"):
            cur.removed += 1
        if len(cur.lines) < max_lines and total < max_total:
            cur.lines.append(line if len(line) <= MAX_LINE else line[:MAX_LINE] + "…")
            total += 1
        else:
            cur.cut += 1
    return files


def _line(text: str) -> str:
    cls = "hunk" if text.startswith("@@") else "add" if text.startswith("+") else \
          "del" if text.startswith("-") else "ctx"
    return f'<span class="{cls}">{html.escape(text)}</span>'


def render_panel(files: list[FileDiff], git_hint: str) -> str:
    if not files:
        return '<div class="panel"><h2>Changes</h2><p class="muted">No changes against the target branch.</p></div>'
    added, removed = sum(f.added for f in files), sum(f.removed for f in files)
    summary = "".join(
        f'<li><code>{html.escape(f.path)}</code> '
        + ('<span class="muted">binary</span>' if f.binary else
           f'<span class="ok">+{f.added}</span> <span class="bad">−{f.removed}</span>') + "</li>"
        for f in files)
    blocks = []
    for f in files:
        if f.binary:
            continue
        rest = (f'<p class="small muted">{f.cut} more lines not shown. All of it: '
                f"<code>{html.escape(git_hint)}</code></p>") if f.cut else ""
        is_open = " open" if f.added + f.removed <= 10 else ""
        blocks.append(f'<details class="file"{is_open}><summary><code>{html.escape(f.path)}</code> '
                      f'<span class="ok">+{f.added}</span> <span class="bad">−{f.removed}</span></summary>'
                      f'<pre class="diff">{"".join(_line(x) for x in f.lines)}</pre>{rest}</details>')
    count = f"{len(files)} file" + ("s" if len(files) != 1 else "")
    return (f'<div class="panel"><h2>Changes · {count} · <span class="ok">+{added}</span> '
            f'<span class="bad">−{removed}</span></h2><ul class="files small">{summary}</ul>{"".join(blocks)}</div>')
