"""Offline HTML overview of a snapshot: index.html plus one page per merge request.
No network: no web fonts, no scripts from elsewhere; images come from uploads/.
Every text from GitLab is escaped; only a small subset of Markdown is turned into
markup (code blocks, inline code, images, links, bold, headings)."""
import html
import re
import shlex
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .snapshot import UPLOAD_RE, MergeRequest, Snapshot, file_name, safe_upload

CSS = """
:root { --bg:#f7f8fa; --surface:#fff; --fg:#1c2230; --muted:#5d6676; --line:#dde2ea;
  --accent:#2d5db0; --code:#eef1f6; --ok:#2c7a4b; --warn:#9a6510; --bad:#b3362c; }
@media (prefers-color-scheme: dark) { :root { --bg:#12151b; --surface:#1a1f28; --fg:#e2e6ed;
  --muted:#9aa3b3; --line:#2d3543; --accent:#80a7ec; --code:#232a36; --ok:#6cc394; --warn:#e2b45c;
  --bad:#ef8a80; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:76rem; margin:0 auto; padding:1.5rem 16px 4rem; display:grid; gap:1.25rem; }
a { color:var(--accent); }
h1 { font-size:1.45rem; line-height:1.3; margin:0; }
h2 { font-size:1.1rem; margin:0; }
.muted { color:var(--muted); }
.small { font-size:.85rem; }
code, pre { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace; font-size:.85rem; }
code { background:var(--code); padding:.05em .3em; border-radius:3px; }
pre { background:var(--code); padding:.7rem .9rem; border-radius:4px; overflow-x:auto; margin:.4rem 0; }
pre code { background:none; padding:0; }
.panel { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:1rem 1.1rem;
  display:grid; gap:.6rem; min-width:0; }
.tablewrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:6px; }
table { border-collapse:collapse; width:100%; }
th, td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:.8rem; color:var(--muted); font-weight:600; white-space:nowrap; }
td.num { font-variant-numeric:tabular-nums; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
.pill { display:inline-block; font-size:.75rem; line-height:1.4; padding:0 .45rem; border-radius:999px;
  border:1px solid var(--line); white-space:nowrap; margin:0 .15rem .15rem 0; }
.ok { color:var(--ok); border-color:var(--ok); } .warn { color:var(--warn); border-color:var(--warn); }
.bad { color:var(--bad); border-color:var(--bad); }
.md { white-space:pre-wrap; overflow-wrap:anywhere; }
.md img { max-width:100%; display:block; margin:.5rem 0; border:1px solid var(--line); }
.md-h { font-weight:700; }
dl.meta { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:.3rem 1rem; margin:0; }
dl.meta dt { color:var(--muted); font-size:.85rem; }
dl.meta dd { margin:0; min-width:0; }
.thread { border-left:3px solid var(--line); padding-left:.8rem; display:grid; gap:.6rem; }
.thread.open { border-left-color:var(--warn); }
.note-head { font-size:.85rem; color:var(--muted); }
details summary { cursor:pointer; color:var(--muted); }
input[type=search] { font:inherit; padding:.4rem .6rem; border:1px solid var(--line); border-radius:4px;
  background:var(--surface); color:var(--fg); width:min(28rem,100%); }
"""

FILTER_JS = """
document.getElementById('filter').addEventListener('input', function (e) {
  var q = e.target.value.toLowerCase();
  document.querySelectorAll('tbody tr').forEach(function (tr) {
    tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) < 0;
  });
});
"""


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def page(title: str, body: str, script: str = "") -> str:
    js = f"<script>{script}</script>" if script else ""
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main>{js}</body></html>\n")


class Markdown:
    """Turns GitLab Markdown into safe HTML. `prefix` leads from the page to the
    snapshot folder ('' for index.html, '../' for mr/<iid>.html)."""

    INLINE = re.compile(r"`([^`\n]+)`|!\[([^\]\n]*)\]\(([^)\s]+)\)|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^*\n]+)\*\*")

    def __init__(self, snap: Snapshot, prefix: str):
        self.snap = snap
        self.prefix = prefix

    def url(self, raw: str) -> str | None:
        """A link target that is safe to put into href/src, or None."""
        if raw.startswith(("https://", "http://")):
            return raw
        if raw.startswith("/") and not raw.startswith("//") and self.snap.web_url:
            return "/".join(self.snap.web_url.split("/")[:3]) + raw   # https://host + /path
        return None

    def upload(self, raw: str) -> tuple[str, str | None, bool] | None:
        """For a link to this project's uploads: (file name, href, is local) - the copy in
        the snapshot when there is one, else the file on GitLab. None for other links."""
        m = UPLOAD_RE.fullmatch(raw)
        if not m or not safe_upload(m.group(1), m.group(2)):
            return None
        name = file_name(m.group(2))
        if self.snap.upload_path(m.group(1), name).is_file():
            return name, f"{self.prefix}uploads/{m.group(1)}/{quote(name)}", True
        online = self.url(f"{self.snap.web_url}/uploads/{m.group(1)}/{quote(name)}") if self.snap.web_url else None
        return name, online, False

    def image(self, alt: str, raw: str) -> str:
        up = self.upload(raw)
        if up:
            name, href, local = up
            if local:
                return f'<a href="{esc(href)}"><img src="{esc(href)}" alt="{esc(alt)}" loading="lazy"></a>'
            label = f"[image not in snapshot: {esc(name)}]"
            return f'<a href="{esc(href)}">{label}</a>' if href else label
        target = self.url(raw)
        return f'<a href="{esc(target)}">[image: {esc(alt or raw)}]</a>' if target else esc(f"![{alt}]({raw})")

    def inline(self, text: str) -> str:
        out, pos = [], 0
        for m in self.INLINE.finditer(text):
            out.append(esc(text[pos:m.start()]))
            code, img_alt, img_url, link_text, link_url, bold = m.groups()
            if code is not None:
                out.append(f"<code>{esc(code)}</code>")
            elif img_url is not None:
                out.append(self.image(img_alt, img_url))
            elif link_url is not None:
                up = self.upload(link_url)
                target = up[1] if up else self.url(link_url)
                out.append(f'<a href="{esc(target)}">{esc(link_text)}</a>' if target else esc(m.group(0)))
            else:
                out.append(f"<strong>{esc(bold)}</strong>")
            pos = m.end()
        out.append(esc(text[pos:]))
        return "".join(out)

    def block(self, text: str | None) -> str:
        if not text:
            return '<div class="md muted">(empty)</div>'
        parts = re.split(r"^```[^\n]*\n(.*?)^```[ \t]*$", text, flags=re.M | re.S)
        out = []
        for i, part in enumerate(parts):
            if i % 2:
                out.append(f"<pre><code>{esc(part.rstrip())}</code></pre>")
                continue
            lines = []
            for line in part.strip("\n").split("\n"):
                h = re.match(r"#{1,6}\s+(.*)", line)
                lines.append(f'<span class="md-h">{self.inline(h.group(1))}</span>' if h else self.inline(line))
            if any(line.strip() for line in lines):
                out.append(f'<div class="md">{chr(10).join(lines)}</div>')
        return "".join(out)


def pipeline_pill(mr: MergeRequest) -> str:
    p = mr.data.get("head_pipeline") or mr.data.get("pipeline")
    if not p:
        return '<span class="muted small">—</span>'
    status = p.get("status", "?")
    cls = {"success": "ok", "failed": "bad", "canceled": "warn", "running": "warn", "pending": "warn"}.get(status, "")
    return f'<span class="pill {cls}">{esc(status)}</span>'


def approval_text(mr: MergeRequest) -> tuple[str, str]:
    """(short text, css class) - 'unknown' when the snapshot has no approvals file."""
    a = mr.approvals
    if a is None:
        return "unknown", ""
    by = [str((x.get("user") or {}).get("username") or "?") for x in a.get("approved_by") or [] if x]
    left = a.get("approvals_left", 0) or 0
    if left == 0 and (by or a.get("approved")):
        return f"approved ({', '.join(by)})" if by else "approved", "ok"
    return (f"{len(by)}/{a.get('approvals_required', '?')}" + (f" ({', '.join(by)})" if by else "")), "warn"


def open_threads(mr: MergeRequest) -> int:
    return sum(1 for d in mr.discussions
               if any(n.get("resolvable") and not n.get("resolved") for n in d.get("notes", [])[:1]))


def users(items) -> str:
    return ", ".join(esc((u or {}).get("username", "")) for u in items or [])


def username(person) -> str:
    return esc((person or {}).get("username"))


def link(snap: Snapshot, raw, text: str) -> str:
    """A link to GitLab, only when the address is a plain http(s) URL."""
    target = Markdown(snap, "").url(raw or "")
    return f'<a href="{esc(target)}">{text}</a>' if target else ""


def render_index(snap: Snapshot) -> str:
    md = Markdown(snap, "")
    rows = []
    for mr in snap.mrs:
        d = mr.data
        appr, appr_cls = approval_text(mr)
        labels = "".join(f'<span class="pill">{esc(lb)}</span>' for lb in d.get("labels") or [])
        draft = '<span class="pill warn">draft</span> ' if d.get("draft") else ""
        threads = open_threads(mr)
        threads_html = f'<span class="pill warn">{threads}</span>' if threads else "0"
        rows.append(
            f'<tr><td class="num"><a href="mr/{mr.iid}.html">!{mr.iid}</a></td>'
            f'<td>{draft}<a href="mr/{mr.iid}.html">{md.inline(d.get("title") or "")}</a>'
            f'<div class="small muted">{esc(d.get("source_branch"))} → {esc(d.get("target_branch"))}</div></td>'
            f'<td>{username(d.get("author"))}</td>'
            f'<td>{users(d.get("reviewers"))}</td>'
            f'<td>{labels}</td>'
            f'<td><span class="pill {appr_cls}">{esc(appr)}</span></td>'
            f"<td>{pipeline_pill(mr)}</td>"
            f'<td class="num">{threads_html}</td>'
            f'<td class="num small">{esc(when(d.get("updated_at"))[:10])}</td></tr>')
    meta = snap.meta
    head = (f"<h1>Merge requests · {esc(meta.get('project', snap.path.name))}</h1>"
            f'<p class="muted small">{len(snap.mrs)} merge requests'
            + (f" with state {esc(meta['state'])}" if meta.get("state") else "")
            + (f" · read {esc(when(meta['fetched_at']))}" if meta.get("fetched_at") else f" · snapshot {esc(snap.path.name)}")
            + (f" · {link(snap, snap.web_url + '/-/merge_requests', 'open in GitLab')}" if snap.web_url else "")
            + " · a snapshot: changes made on GitLab after the read are not in here</p>")
    failures = meta.get("failures") or []
    warn = (f'<div class="panel"><strong class="bad">Not complete:</strong>'
            f'<div class="small">{"<br>".join(esc(f) for f in failures)}</div></div>') if failures else ""
    if snap.complete is False:
        warn = ('<div class="panel"><strong class="bad">This read did not finish.</strong>'
                '<div class="small">It was interrupted; merge requests without their own data show only '
                "what the list had. Run mr-export fetch again for a full snapshot.</div></div>") + warn
    table = ('<div class="tablewrap"><table><thead><tr><th>MR</th><th>Title · branches</th><th>Author</th>'
             "<th>Reviewers</th><th>Labels</th><th>Approvals</th><th>Pipeline</th><th>Open threads</th>"
             f'<th>Updated</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    search = '<input type="search" id="filter" placeholder="Filter: title, branch, person, label …" aria-label="Filter">'
    return page(f"MRs {meta.get('project', '')}", head + warn + search + table, FILTER_JS)


def render_note(md: Markdown, note: dict) -> str:
    head = f'{username(note.get("author"))} · {esc(when(note.get("created_at")))}'
    return f'<div><div class="note-head">{head}</div>{md.block(note.get("body"))}</div>'


def position_text(note: dict) -> str:
    p = note.get("position") or {}
    path = p.get("new_path") or p.get("old_path")
    line = p.get("new_line") or p.get("old_line")
    return f"{path}:{line}" if path and line else (path or "")


def render_mr(snap: Snapshot, mr: MergeRequest) -> str:
    md = Markdown(snap, "../")
    d = mr.data
    target, iid = d.get("target_branch") or "dev", mr.iid
    appr, appr_cls = approval_text(mr)
    base = shlex.quote(f"origin/{target}")   # branch names may hold shell characters
    git = (f"git fetch origin refs/merge-requests/{iid}/head:refs/remotes/origin/mr/{iid}\n"
           f"git log --oneline {base}..origin/mr/{iid}\n"
           f"git diff {base}...origin/mr/{iid}")
    meta = (
        '<dl class="meta">'
        f"<dt>Branches</dt><dd><code>{esc(d.get('source_branch'))}</code> → <code>{esc(target)}</code></dd>"
        f"<dt>Author</dt><dd>{username(d.get('author'))}</dd>"
        f"<dt>Assignees</dt><dd>{users(d.get('assignees')) or '—'}</dd>"
        f"<dt>Reviewers</dt><dd>{users(d.get('reviewers')) or '—'}</dd>"
        f"<dt>Labels</dt><dd>{''.join(f'<span class=pill>{esc(lb)}</span>' for lb in d.get('labels') or []) or '—'}</dd>"
        f'<dt>Approvals</dt><dd><span class="pill {appr_cls}">{esc(appr)}</span></dd>'
        f"<dt>Pipeline</dt><dd>{pipeline_pill(mr)}</dd>"
        f"<dt>Merge status</dt><dd>{esc(d.get('detailed_merge_status') or d.get('merge_status') or '—')}</dd>"
        f"<dt>Created · updated</dt><dd>{esc(when(d.get('created_at')))} · {esc(when(d.get('updated_at')))}</dd>"
        f"<dt>Head commit</dt><dd><code>{esc((d.get('sha') or '')[:12])}</code></dd>"
        "</dl>")
    threads, activity = [], []
    for disc in mr.discussions:
        notes = disc.get("notes", [])
        if not notes:
            continue
        if notes[0].get("system"):
            activity += [f'<div class="small"><span class="muted">{esc(when(n.get("created_at")))} · '
                         f'{username(n.get("author"))}</span> {md.inline(n.get("body") or "")}</div>'
                         for n in notes]
            continue
        first = notes[0]
        is_open = first.get("resolvable") and not first.get("resolved")
        state = ('<span class="pill warn">open</span>' if is_open
                 else '<span class="pill ok">resolved</span>' if first.get("resolvable") else "")
        where = position_text(first)
        where_html = f" <code>{esc(where)}</code>" if where else ""
        threads.append(f'<div class="thread{" open" if is_open else ""}"><div>{state}{where_html}</div>'
                       + "".join(render_note(md, n) for n in notes) + "</div>")
    partial = snap.failed(iid) or (snap.complete is False and mr.approvals is None)
    warn = ('<div class="panel"><strong class="bad">Not all data of this merge request could be read.</strong>'
            '<div class="small">Threads or approvals may be missing; see the top of the overview.</div></div>'
            if partial else "")
    body = (
        f'<p class="small"><a href="../index.html">← all merge requests</a>'
        + (f" · {link(snap, d.get('web_url'), 'open in GitLab')}" if d.get("web_url") else "") + "</p>"
        f"<h1>!{iid} {md.inline(d.get('title') or '')}</h1>{warn}"
        f'<div class="panel">{meta}</div>'
        f'<div class="panel"><h2>Look at the code without GitLab</h2><pre><code>{esc(git)}</code></pre>'
        '<p class="small muted">The first line fetches the MR\'s commits over SSH. The three dots in '
        "<code>git diff</code> show only what the MR changes since it branched off.</p></div>"
        f'<div class="panel"><h2>Description</h2>{md.block(d.get("description"))}</div>'
        f'<div class="panel"><h2>Threads ({len(threads)})</h2>'
        + ("".join(threads) or '<p class="muted">No comments.</p>') + "</div>"
        + (f'<details class="panel"><summary>Activity ({len(activity)})</summary>{"".join(activity)}</details>'
           if activity else ""))
    return page(f"!{iid} {d.get('title') or ''}", body)


def render(snap: Snapshot) -> Path:
    """Writes index.html and mr/<iid>.html into the snapshot; returns index.html."""
    (snap.path / "mr").mkdir(exist_ok=True)
    for mr in snap.mrs:
        (snap.path / "mr" / f"{mr.iid}.html").write_text(render_mr(snap, mr), encoding="utf-8")
    index = snap.path / "index.html"
    index.write_text(render_index(snap), encoding="utf-8")
    return index
