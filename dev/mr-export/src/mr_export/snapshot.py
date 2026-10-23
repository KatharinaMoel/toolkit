"""Layout of a snapshot folder and reading it back.

<snapshot>/meta.json                    project, host, state, time of the read
<snapshot>/mrs.ndjson                   the list as GitLab returned it
<snapshot>/mr/<iid>.json                one merge request with its head pipeline
<snapshot>/mr/<iid>-discussions.ndjson  threads and system notes
<snapshot>/mr/<iid>-approvals.json      approval state
<snapshot>/uploads/<secret>/<file>      images referenced in texts

A flat folder (mrs-list.ndjson, mr-<iid>.json, mr-<iid>-discussions.ndjson) is
read as well, so a hand-made read with plain glab calls can be rendered too.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

# GitLab upload links of this project: a relative /uploads/<32 hex>/<file name> at the
# start of a link target; absolute URLs (other projects) are left alone.
UPLOAD_RE = re.compile(r"(?:^|(?<=[(\"'\s]))/uploads/([0-9a-f]{32})/([^/\s)\"'<>]+)")


@dataclass
class MergeRequest:
    data: dict
    discussions: list[dict] = field(default_factory=list)
    approvals: dict | None = None

    @property
    def iid(self) -> int:
        return int(self.data["iid"])


@dataclass
class Snapshot:
    path: Path
    meta: dict
    mrs: list[MergeRequest]

    @property
    def complete(self) -> bool | None:
        """False for a read that did not finish, None when the folder has no meta.json."""
        return self.meta.get("complete") if "complete" in self.meta else None

    def failed(self, iid: int) -> bool:
        return iid in self.meta.get("failed_iids", [])

    @property
    def web_url(self) -> str:
        return self.meta.get("web_url", "")

    def upload_path(self, secret: str, name: str) -> Path:
        return self.path / "uploads" / secret / name


def parse_ndjson(data: bytes | str) -> list[dict]:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_ndjson(path: Path) -> list[dict]:
    return parse_ndjson(path.read_text(encoding="utf-8"))


def file_name(raw: str) -> str:
    """Markdown may carry the name percent-encoded; the file on disk has the plain name."""
    return unquote(raw)


def safe_upload(secret: str, name: str) -> bool:
    """Only names that stay inside uploads/<secret>/ are ever written or read."""
    name = file_name(name)
    return (re.fullmatch(r"[0-9a-f]{32}", secret) is not None and name not in ("", ".", "..")
            and "/" not in name and "\\" not in name and not name.startswith("."))


def upload_refs(mr: MergeRequest) -> list[tuple[str, str]]:
    """Every distinct (secret, plain file name) referenced in description and notes."""
    texts = [mr.data.get("description") or ""]
    for d in mr.discussions:
        texts += [n.get("body") or "" for n in d.get("notes", [])]
    seen: dict[tuple[str, str], None] = {}
    for text in texts:
        for secret, name in UPLOAD_RE.findall(text):
            if safe_upload(secret, name):
                seen[(secret, file_name(name))] = None
    return list(seen)


def _first(*paths: Path) -> Path | None:
    return next((p for p in paths if p.is_file()), None)


def load(path: Path) -> Snapshot:
    listing = _first(path / "mrs.ndjson", path / "mrs-list.ndjson")
    if listing is None:
        raise FileNotFoundError(f"no merge request list (mrs.ndjson) in {path}")
    meta_file = path / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
    mrs = []
    for item in read_ndjson(listing):
        iid = item["iid"]
        detail = _first(path / "mr" / f"{iid}.json", path / f"mr-{iid}.json")
        data = json.loads(detail.read_text(encoding="utf-8")) if detail else item
        disc = _first(path / "mr" / f"{iid}-discussions.ndjson", path / f"mr-{iid}-discussions.ndjson")
        appr = _first(path / "mr" / f"{iid}-approvals.json", path / f"mr-{iid}-approvals.json")
        mrs.append(MergeRequest(
            data=data,
            discussions=read_ndjson(disc) if disc else [],
            approvals=json.loads(appr.read_text(encoding="utf-8")) if appr else None,
        ))
    if not meta.get("web_url") and mrs:
        # https://host/group/project/-/merge_requests/835 -> https://host/group/project
        meta["web_url"] = mrs[0].data.get("web_url", "").split("/-/merge_requests/")[0]
    if not meta.get("project") and meta.get("web_url"):
        meta["project"] = "/".join(meta["web_url"].split("/")[3:])   # group/project
    mrs.sort(key=lambda m: m.iid, reverse=True)
    return Snapshot(path=path, meta=meta, mrs=mrs)
