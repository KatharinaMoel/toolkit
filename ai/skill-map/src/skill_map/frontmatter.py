"""Read the first front matter block and the kios marker, without a YAML library."""
import re

_KEY = re.compile(r"^([A-Za-z0-9_-]+):[ \t]*(.*)$")
_ITEM = re.compile(r"^[ \t]+-[ \t]*(.*)$")
KIOS_MARK = b"kios:generated | Quelle: "


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def front_matter(data: bytes, limit: int = 4096) -> dict[str, str | list[str]]:
    """Keys of the first --- block; flow lists [a, b] and block lists (- a) become lists.

    Only the first `limit` bytes are read. Metadata, not the text itself, so an invalid
    UTF-8 byte is replaced here (the text rules handle the file)."""
    lines = data[:limit].decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str | list[str]] = {}
    items: list[str] | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = _ITEM.match(line)
        if items is not None and m:
            items.append(_unquote(m.group(1)))
            continue
        items = None
        m = _KEY.match(line)
        if not m or m.group(1) in out:   # the first value of a key wins
            continue
        key, value = m.group(1), m.group(2).strip()
        if value == "":
            items = []
            out[key] = items
        elif value.startswith("[") and value.endswith("]"):
            out[key] = [_unquote(v) for v in value[1:-1].split(",") if v.strip()]
        else:
            out[key] = _unquote(value)
    return {k: ("" if v == [] else v) for k, v in out.items()}


def kios_source(data: bytes) -> str | None:
    """The source path that kios sync wrote into a generated file, as kios finds it:
    the marker within the first 2000 bytes, the value up to the next " |"."""
    i = data.find(KIOS_MARK, 0, 2000 + len(KIOS_MARK))
    if i < 0 or i >= 2000:
        return None
    rest = data[i + len(KIOS_MARK):i + len(KIOS_MARK) + 512]
    j = rest.find(b" |")
    value = (rest[:j] if j >= 0 else rest.split(b"\n")[0]).decode("utf-8", "replace").strip()
    return value or None
